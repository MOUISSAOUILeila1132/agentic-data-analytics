import json
import math
import threading
import uuid
import warnings

import pandas as pd

from app.services.dataset_service import _q, dataset_dir, open_connection

# Au-delà, le nombre de valeurs distinctes est estimé (HyperLogLog) au lieu d'être exact.
EXACT_DISTINCT_MAX_ROWS = 5_000_000

_NUMERIC_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
    "FLOAT", "DOUBLE", "REAL", "DECIMAL",
}
_FLOAT_TYPES = {"FLOAT", "DOUBLE", "REAL"}

# Formats de dates courants que le cast ISO de DuckDB ne reconnaît pas
_DATE_FORMATS = (
    "['%d/%m/%Y', '%d/%m/%Y %H:%M', '%d/%m/%Y %H:%M:%S', "
    "'%d-%m-%Y', '%m/%d/%Y', '%Y/%m/%d']"
)


def _num(x):
    """Convertit en float JSON-safe (None si NaN/inf)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _date_expr(col: str) -> str:
    """Expression SQL qui tente de lire une chaîne comme date/heure (NULL sinon)."""
    return f"COALESCE(TRY_CAST({col} AS TIMESTAMP), TRY_STRPTIME({col}, {_DATE_FORMATS}))"


def _kind_from_type(duck_type: str) -> str:
    t = duck_type.upper()
    base = t.split("(")[0].strip()
    if "[" in t or base in ("STRUCT", "MAP", "LIST", "UNION", "BLOB", "BIT"):
        return "text"
    if base == "BOOLEAN":
        return "boolean"
    if base in _NUMERIC_TYPES:
        return "numeric"
    if base == "DATE" or base.startswith("TIMESTAMP"):
        return "temporal"
    return "string"  # VARCHAR & co : on tranche plus bas (temporel / catégoriel / texte)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else (None if value is None else str(value))


def _profile_column(con, name: str, duck_type: str, rows: int) -> dict:
    q = _q(name)
    kind = _kind_from_type(duck_type)
    base_type = duck_type.upper().split("(")[0].strip()
    # NaN flottants = valeurs manquantes (comme pandas)
    x = f"CASE WHEN isnan({q}) THEN NULL ELSE {q} END" if base_type in _FLOAT_TYPES else q
    distinct = f"count(DISTINCT {x})" if rows <= EXACT_DISTINCT_MAX_ROWS else f"approx_count_distinct({x})"

    missing, unique = con.execute(
        f"SELECT count(*) FILTER (WHERE {x} IS NULL), {distinct} FROM data"
    ).fetchone()
    missing, unique = int(missing), int(unique)
    non_null = rows - missing
    unique = min(unique, non_null)  # l'estimation (HyperLogLog) peut légèrement dépasser

    info = {
        "name": name,
        "kind": kind,
        "dtype": duck_type,
        "missing": missing,
        "missing_pct": round(100 * missing / rows, 2) if rows else 0.0,
        "unique": unique,
    }
    if non_null == 0:
        info["kind"] = "empty"
        return info

    # --- Chaînes : date stockée en texte ? catégorielle ? texte libre ? ---
    string_dates = False
    if kind == "string":
        share, avg_len = con.execute(
            f"SELECT avg(CASE WHEN {_date_expr('v')} IS NOT NULL THEN 1.0 ELSE 0.0 END), avg(length(v)) "
            f"FROM (SELECT {q} AS v FROM data WHERE {q} IS NOT NULL LIMIT 500)"
        ).fetchone()
        if share is not None and share > 0.9:
            kind, string_dates = "temporal", True
        elif unique <= max(20, 0.05 * non_null):
            kind = "categorical"
        else:
            kind = "text" if (avg_len or 0) > 30 else "categorical"
        info["kind"] = kind

    if kind == "numeric":
        d = f"CAST({x} AS DOUBLE)"
        mn, mx, mean, med, std, q1, q3 = con.execute(
            f"SELECT min({d}), max({d}), avg({d}), median({d}), stddev_samp({d}), "
            f"quantile_cont({d}, 0.25), quantile_cont({d}, 0.75) FROM data"
        ).fetchone()
        outliers = 0
        if q1 is not None and q3 is not None and math.isfinite(q1) and math.isfinite(q3) and q3 > q1:
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = int(con.execute(
                f"SELECT count(*) FROM data WHERE {d} < {lo!r} OR {d} > {hi!r}"
            ).fetchone()[0])
        info["stats"] = {
            "min": _num(mn), "max": _num(mx), "mean": _num(mean),
            "median": _num(med), "std": _num(std), "q1": _num(q1), "q3": _num(q3),
        }
        info["outliers_iqr"] = outliers  # signalées, jamais supprimées

    elif kind == "categorical":
        top = con.execute(
            f"SELECT CAST({q} AS VARCHAR) AS v, count(*) AS c FROM data "
            f"WHERE {q} IS NOT NULL GROUP BY 1 ORDER BY c DESC, v ASC LIMIT 5"
        ).fetchall()
        info["top_values"] = [{"value": v, "count": int(c)} for v, c in top]

    elif kind == "temporal":
        if string_dates:
            mn, mx = con.execute(f"SELECT min(p), max(p) FROM (SELECT {_date_expr(q)} AS p FROM data)").fetchone()
        else:
            mn, mx = con.execute(f"SELECT min({q}), max({q}) FROM data").fetchone()
        if mn is not None and mx is not None:
            info["range"] = {"min": _iso(mn), "max": _iso(mx)}

    return info


def profile_dataset(dataset_id: str) -> dict:
    """Profil qualité calculé par DuckDB directement sur le Parquet (aucun DataFrame)."""
    con = open_connection(dataset_id)
    try:
        rows = int(con.execute("SELECT count(*) FROM data").fetchone()[0])
        schema = [(r[0], r[1]) for r in con.execute("DESCRIBE data").fetchall()]
        columns = [_profile_column(con, name, dtype, rows) for name, dtype in schema]
        # Doublons : lignes hachées (64 bits) -> exact en pratique, mémoire faible
        duplicates = int(con.execute("SELECT count(*) - count(DISTINCT hash(t)) FROM data t").fetchone()[0]) if rows else 0
    finally:
        con.close()
    return _build_report(rows, len(schema), duplicates, columns)


def _build_report(rows: int, n_cols: int, duplicates: int, columns: list[dict]) -> dict:
    warns = []
    if duplicates:
        warns.append(f"{duplicates} ligne(s) dupliquée(s) détectée(s).")
    for c in columns:
        if c["kind"] == "empty":
            warns.append(f"La colonne « {c['name']} » est entièrement vide.")
            continue
        if c["missing_pct"] > 20:
            warns.append(f"« {c['name']} » : {c['missing_pct']} % de valeurs manquantes.")
        if c["unique"] <= 1:
            warns.append(f"« {c['name']} » est constante.")
        elif c["kind"] == "categorical" and c.get("top_values"):
            share = c["top_values"][0]["count"] / max(rows - c["missing"], 1)
            if share > 0.95:
                warns.append(f"« {c['name']} » est très déséquilibrée ({share:.0%} pour une seule valeur).")
        if c.get("outliers_iqr"):
            warns.append(
                f"« {c['name']} » : {c['outliers_iqr']} valeur(s) potentiellement aberrante(s) "
                f"(méthode IQR) — non supprimées, à valider."
            )
    return {
        "rows": rows,
        "columns_count": n_cols,
        "duplicate_rows": duplicates,
        "columns": columns,
        "warnings": warns,
    }


_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(dataset_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(dataset_id, threading.Lock())


def _read_cache(cache):
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # absent ou corrompu : on recalcule


def get_profile(dataset_id: str) -> dict:
    """Profil mis en cache dans profile.json : calculé une seule fois par dataset.

    Le verrou évite deux calculs simultanés dans le même processus (l'API) ; l'écriture
    atomique avec fichier temporaire unique protège aussi entre processus (API / serveur MCP).
    """
    folder = dataset_dir(dataset_id)
    cache = folder / "profile.json"
    cached = _read_cache(cache)
    if cached is not None:
        return cached
    with _lock_for(dataset_id):
        cached = _read_cache(cache)
        if cached is not None:
            return cached
        profile = profile_dataset(dataset_id)
        tmp = folder / f"profile.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache)  # écriture atomique
        return profile


# =========================================================================== #
# Ancienne version pandas — conservée pour compatibilité (petits DataFrames).
# Ne pas l'utiliser sur de gros datasets : tout est chargé en mémoire.
# =========================================================================== #

def infer_kind(s: pd.Series) -> str:
    if pd.api.types.is_bool_dtype(s):
        return "boolean"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "temporal"
    non_null = s.dropna()
    if non_null.empty:
        return "empty"
    sample = non_null.astype(str).head(500)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce")
    if parsed.notna().mean() > 0.9:
        return "temporal"
    if non_null.nunique() <= max(20, 0.05 * len(non_null)):
        return "categorical"
    return "text" if sample.str.len().mean() > 30 else "categorical"


def profile_column(s: pd.Series) -> dict:
    n = len(s)
    kind = infer_kind(s)
    missing = int(s.isna().sum())
    info = {
        "name": s.name,
        "kind": kind,
        "dtype": str(s.dtype),
        "missing": missing,
        "missing_pct": round(100 * missing / n, 2) if n else 0.0,
        "unique": int(s.nunique(dropna=True)),
    }
    non_null = s.dropna()

    if kind == "numeric" and not non_null.empty:
        x = non_null.astype(float)
        q1, q3 = x.quantile(0.25), x.quantile(0.75)
        iqr = q3 - q1
        outliers = int(((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
        info["stats"] = {
            "min": _num(x.min()), "max": _num(x.max()), "mean": _num(x.mean()),
            "median": _num(x.median()), "std": _num(x.std()),
            "q1": _num(q1), "q3": _num(q3),
        }
        info["outliers_iqr"] = outliers  # signalées, jamais supprimées
    elif kind == "categorical":
        top = non_null.astype(str).value_counts().head(5)
        info["top_values"] = [{"value": k, "count": int(v)} for k, v in top.items()]
    elif kind == "temporal":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            dates = pd.to_datetime(non_null, errors="coerce").dropna()
        if not dates.empty:
            info["range"] = {"min": dates.min().isoformat(), "max": dates.max().isoformat()}
    return info


def profile_dataframe(df: pd.DataFrame) -> dict:
    columns = [profile_column(df[c]) for c in df.columns]
    duplicates = int(df.duplicated().sum())
    warns = []

    if duplicates:
        warns.append(f"{duplicates} ligne(s) dupliquée(s) détectée(s).")
    for c in columns:
        if c["kind"] == "empty":
            warns.append(f"La colonne « {c['name']} » est entièrement vide.")
            continue
        if c["missing_pct"] > 20:
            warns.append(f"« {c['name']} » : {c['missing_pct']} % de valeurs manquantes.")
        if c["unique"] <= 1:
            warns.append(f"« {c['name']} » est constante.")
        elif c["kind"] == "categorical" and c.get("top_values"):
            share = c["top_values"][0]["count"] / max(len(df) - c["missing"], 1)
            if share > 0.95:
                warns.append(f"« {c['name']} » est très déséquilibrée ({share:.0%} pour une seule valeur).")
        if c.get("outliers_iqr"):
            warns.append(
                f"« {c['name']} » : {c['outliers_iqr']} valeur(s) potentiellement aberrante(s) "
                f"(méthode IQR) — non supprimées, à valider."
            )

    return {
        "rows": int(df.shape[0]),
        "columns_count": int(df.shape[1]),
        "duplicate_rows": duplicates,
        "columns": columns,
        "warnings": warns,
    }