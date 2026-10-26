"""Service Dashboard : construit un tableau de bord interactif directement avec DuckDB.

Principe (cahier des charges, Module 5 + RF-06 / RF-07) :
- le CODE choisit les graphiques candidats selon les types de colonnes
  et calcule tous les chiffres (SQL DuckDB généré par le code, jamais par le LLM) ;
- chaque widget garde son SQL et son résultat (traçabilité) ;
- une couche de vérification recoupe les totaux (somme de Kahan, somme des barres).
Le LLM pourra ensuite SÉLECTIONNER / ORDONNER / COMMENTER les widgets, pas calculer.

Gros datasets : plus aucun DataFrame complet. Les colonnes sont classées à partir du profil mis
en cache, tout est calculé en SQL sur le Parquet, et seuls des résultats agrégés (barres, séries,
tranches d'histogramme, matrice de corrélation) arrivent en pandas / Plotly.
"""
from __future__ import annotations

import math
import re
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app.services.profiling_service import _date_expr

MAX_DIM_CARDINALITY = 30  # au-delà : colonne texte/identifiant, pas une dimension
TOP_N = 10
HIST_BINS = 30            # tranches de l'histogramme (calculées en SQL)
MAX_CORR_COLUMNS = 20     # la matrice de corrélation est limitée à N colonnes numériques
MEASURE_HINTS = {
    "montant", "amount", "revenue", "revenu", "ca", "total", "prix", "price",
    "sales", "vente", "ventes", "cost", "cout", "coût", "salaire", "salary",
}
_INTEGER_TYPES = {
    "TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT",
    "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT",
}


# ----------------------------------------------------------------- structures
@dataclass
class ColumnKinds:
    numeric: list[str] = field(default_factory=list)
    categorical: list[str] = field(default_factory=list)
    temporal: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    string_dates: list[str] = field(default_factory=list)  # colonnes temporelles stockées en texte
    booleans: list[str] = field(default_factory=list)      # colonnes booléennes (rangées dans `categorical`)


@dataclass
class Widget:
    id: str
    title: str
    kind: str  # bar | line | hist | heatmap
    sql: str
    data: pd.DataFrame
    figure: go.Figure


@dataclass
class Dashboard:
    kpis: list[tuple[str, str]]
    widgets: list[Widget]
    warnings: list[str]
    measure: str | None
    kinds: ColumnKinds
    rows: int = 0  # lignes après filtrage


# -------------------------------------------------------------------- helpers
def _q(name: str) -> str:
    """Quote un identifiant SQL (évite toute injection via un nom de colonne)."""
    return '"' + str(name).replace('"', '""') + '"'


def fmt_num(x: float, decimals: int = 2) -> str:
    s = f"{x:,.{decimals}f}".replace(",", "\u202f").replace(".", ",")
    return s


def text_expr(kinds: ColumnKinds, col: str) -> str:
    """Expression SQL « valeur en texte » d'une colonne catégorielle (booléens : 'True' / 'False')."""
    q = _q(col)
    return f"CASE WHEN {q} THEN 'True' ELSE 'False' END" if col in kinds.booleans else f"CAST({q} AS VARCHAR)"


def as_date(value) -> date:
    """date ou datetime (DuckDB / pandas) -> date."""
    return value.date() if isinstance(value, datetime) else value


def pick_measure(kinds: ColumnKinds) -> str | None:
    """Mesure principale : colonne numérique dont le nom évoque un montant, sinon la 1re."""
    for c in kinds.numeric:
        tokens = set(re.split(r"[^a-z0-9àâéèêîôûç]+", str(c).lower()))
        if tokens & MEASURE_HINTS:
            return c
    return kinds.numeric[0] if kinds.numeric else None


def _where(conds: list[str], *extra: str) -> str:
    parts = [*conds, *extra]
    return " WHERE " + " AND ".join(parts) if parts else ""


# ------------------------------------------------- classification des colonnes
def classify_from_profile(profile: dict) -> ColumnKinds:
    """Classe les colonnes à partir du profil mis en cache (aucune lecture des données)."""
    kinds, n = ColumnKinds(), int(profile["rows"])
    for c in profile["columns"]:
        name, kind, nun = c["name"], c["kind"], int(c["unique"])
        base = str(c["dtype"]).upper().split("(")[0].strip()
        if kind == "empty" or nun == 0:
            kinds.ignored.append(name)
        elif kind == "boolean":
            kinds.categorical.append(name)
            kinds.booleans.append(name)
        elif kind == "temporal":
            kinds.temporal.append(name)
            if base == "VARCHAR":
                kinds.string_dates.append(name)
        elif kind == "numeric":
            is_id = base in _INTEGER_TYPES and n > 50 and nun > 0.95 * n
            (kinds.ignored if is_id else kinds.numeric).append(name)
        elif 2 <= nun <= MAX_DIM_CARDINALITY:
            kinds.categorical.append(name)
        else:
            kinds.ignored.append(name)
    return kinds


def prepare_view(con: duckdb.DuckDBPyConnection, kinds: ColumnKinds, source: str = "raw") -> None:
    """Crée la vue `data` : celle de `source`, avec les dates stockées en texte converties."""
    if kinds.string_dates:
        repl = ", ".join(f"{_date_expr(_q(c))} AS {_q(c)}" for c in kinds.string_dates)
        con.execute(f"CREATE VIEW data AS SELECT * REPLACE ({repl}) FROM {source}")
    else:
        con.execute(f"CREATE VIEW data AS SELECT * FROM {source}")


# --------------------------------------------------------------------- build
def build_dashboard_sql(
    con: duckdb.DuckDBPyConnection, kinds: ColumnKinds, conds: list[str] | tuple[str, ...] = ()
) -> Dashboard:
    """Construit le dashboard à partir de la vue/table `data` de `con`, filtrée par `conds`."""
    conds = list(conds)
    w = _where(conds)
    all_cols = [r[0] for r in con.execute("DESCRIBE data").fetchall()]
    n_cols = len(all_cols)

    rows = int(con.execute(f"SELECT count(*) FROM data{w}").fetchone()[0])
    if rows == 0:
        return Dashboard([("Lignes", "0")], [], ["Aucune ligne après filtrage."], None, kinds, rows=0)

    warns: list[str] = []
    m = pick_measure(kinds)
    dm = f"CAST({_q(m)} AS DOUBLE)" if m else None
    agg = f"SUM({dm})" if m else "COUNT(*)"
    agg_label = f"Somme de {m}" if m else "Nombre de lignes"
    d0 = kinds.categorical[0] if kinds.categorical else None

    # ---- KPI : une seule passe sur les données
    select = ["(" + " + ".join(f"count(*) FILTER (WHERE {_q(c)} IS NULL)" for c in all_cols) + ")"]
    if m:
        select += [f"sum({dm})", f"fsum({dm})", f"avg({dm})", f"count(*) FILTER (WHERE {dm} < 0)"]
    if d0:
        select.append(f"count(DISTINCT {_q(d0)})")
    values = list(con.execute(f"SELECT {', '.join(select)} FROM data{w}").fetchone())

    missing_pct = int(values.pop(0)) / (rows * n_cols) * 100
    kpis = [
        ("Lignes", fmt_num(rows, 0)),
        ("Colonnes", fmt_num(n_cols, 0)),
        ("Valeurs manquantes", f"{missing_pct:.1f} %"),
    ]
    total = 0.0
    if m:
        total_raw, ref_raw, mean_raw, n_neg = values[:4]
        del values[:4]
        total, ref = float(total_raw or 0.0), float(ref_raw or 0.0)
        kpis += [
            (f"Total {m}", fmt_num(total)),
            (f"Moyenne {m}", fmt_num(float(mean_raw)) if mean_raw is not None else "—"),
        ]
        # recoupement : somme standard vs somme de Kahan (deux algorithmes indépendants)
        if not math.isclose(total, ref, rel_tol=1e-9, abs_tol=1e-6):
            warns.append(f"Incohérence sur le total de {m} (SUM ≠ somme de Kahan).")
        if n_neg:
            warns.append(f"« {m} » contient des valeurs négatives (retours/remises ?) : "
                         "les classements et totaux en tiennent compte.")
    if d0:
        kpis.append((f"{d0} distincts", fmt_num(int(values[0]), 0)))

    widgets: list[Widget] = []

    # ---- barres Top N par dimension catégorielle (max 3)
    for d in kinds.categorical[:3]:
        # tri secondaire sur la modalité : classement déterministe en cas d'égalité
        sql = (
            f"SELECT COALESCE(CAST({_q(d)} AS VARCHAR), '(manquant)') AS {_q(d)}, "
            f"{agg} AS valeur FROM data{w} GROUP BY 1 ORDER BY valeur DESC, 1 LIMIT {TOP_N}"
        )
        res = con.execute(sql).df()
        fig = px.bar(res, x="valeur", y=d, orientation="h", text_auto=".3s",
                     title=f"{agg_label} par {d}", labels={"valeur": agg_label})
        fig.update_yaxes(autorange="reversed")
        widgets.append(Widget(f"bar_{d}", f"{agg_label} par {d}", "bar", sql, res, fig))
        # vérification : sans troncature, la somme des barres = total
        if m:
            n_distinct, n_null = con.execute(
                f"SELECT count(DISTINCT {_q(d)}), count(*) FILTER (WHERE {_q(d)} IS NULL) FROM data{w}"
            ).fetchone()
            if n_distinct + (1 if n_null else 0) <= TOP_N:
                if not math.isclose(float(res["valeur"].sum()), total, rel_tol=1e-9, abs_tol=1e-6):
                    warns.append(f"Le graphique « par {d} » ne correspond pas au total.")

    # ---- série temporelle
    for t in kinds.temporal[:1]:
        wt = _where(conds, f"{_q(t)} IS NOT NULL")
        lo, hi = con.execute(f"SELECT min({_q(t)}), max({_q(t)}) FROM data{wt}").fetchone()
        if lo is None:
            continue
        span = (hi - lo).days
        grain = "day" if span <= 60 else ("month" if span <= 365 * 5 else "year")
        sql = (
            f"SELECT date_trunc('{grain}', {_q(t)}) AS periode, {agg} AS valeur "
            f"FROM data{wt} GROUP BY 1 ORDER BY 1"
        )
        res = con.execute(sql).df()
        fig = px.line(res, x="periode", y="valeur", markers=True,
                      title=f"{agg_label} dans le temps ({grain})", labels={"valeur": agg_label})
        widgets.append(Widget(f"line_{t}", f"{agg_label} dans le temps", "line", sql, res, fig))

    # ---- distribution de la mesure : tranches calculées en SQL (jamais 15 M de points dans Plotly)
    if m:
        lo, hi, n_valid = con.execute(f"SELECT min({dm}), max({dm}), count({dm}) FROM data{w}").fetchone()
        if n_valid and lo is not None and math.isfinite(lo) and math.isfinite(hi):
            nb, width = (HIST_BINS, (hi - lo) / HIST_BINS) if hi > lo else (1, 1.0)
            bin_expr = f"LEAST(CAST(floor(({dm} - {lo!r}) / {width!r}) AS INTEGER), {nb - 1})"
            wm = _where(conds, f"{dm} IS NOT NULL")
            sql = f"SELECT {bin_expr} AS tranche, COUNT(*) AS effectif FROM data{wm} GROUP BY 1 ORDER BY 1"
            counts = dict(con.execute(sql).fetchall())
            starts = [lo + i * width for i in range(nb)]
            res = pd.DataFrame({
                "debut": starts,
                "fin": [s + width for s in starts],
                "effectif": [int(counts.get(i, 0)) for i in range(nb)],
            })
            plot = res.assign(centre=(res["debut"] + res["fin"]) / 2)
            fig = px.bar(plot, x="centre", y="effectif", hover_data=["debut", "fin"],
                         title=f"Distribution de {m}", labels={"centre": m, "effectif": "Effectif"})
            fig.update_layout(bargap=0)
            widgets.append(Widget(f"hist_{m}", f"Distribution de {m}", "hist", sql, res, fig))

    # ---- corrélations : calculées en SQL (une passe), limitées aux premières colonnes numériques
    if len(kinds.numeric) >= 3:
        num = kinds.numeric[:MAX_CORR_COLUMNS]
        pairs = [(i, j) for i in range(len(num)) for j in range(i + 1, len(num))]
        exprs = [f"corr(CAST({_q(num[i])} AS DOUBLE), CAST({_q(num[j])} AS DOUBLE))" for i, j in pairs]
        vals = con.execute(f"SELECT {', '.join(exprs)} FROM data{w}").fetchone()
        mat = np.full((len(num), len(num)), np.nan)
        np.fill_diagonal(mat, 1.0)
        for (i, j), v in zip(pairs, vals):
            if v is not None and math.isfinite(v):
                mat[i, j] = mat[j, i] = v
        corr = pd.DataFrame(mat, index=num, columns=num)
        fig = px.imshow(corr, text_auto=".2f", zmin=-1, zmax=1,
                        color_continuous_scale="RdBu", title="Corrélations")
        sql = f"-- DuckDB : corr(x, y) pour chacune des {len(pairs)} paires de colonnes numériques"
        widgets.append(Widget("corr", "Corrélations", "heatmap", sql, corr.reset_index(), fig))
        if len(kinds.numeric) > MAX_CORR_COLUMNS:
            warns.append(f"Corrélations limitées aux {MAX_CORR_COLUMNS} premières colonnes numériques.")

    return Dashboard(kpis, widgets, warns, m, kinds, rows=rows)


# ------------------------------------------- compatibilité : anciennes fonctions pandas
# Conservées pour les petits DataFrames (tests, scripts) : même résultat, calculé via DuckDB.
def _looks_like_date(s: pd.Series) -> bool:
    sample = s.dropna().astype(str).head(200)
    if sample.empty or sample.str.contains(r"[-/]").mean() < 0.9:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce")
    return parsed.notna().mean() > 0.9


def classify_columns(df: pd.DataFrame) -> ColumnKinds:
    kinds, n = ColumnKinds(), len(df)
    for c in df.columns:
        s = df[c]
        nun = s.nunique(dropna=True)
        if nun == 0:
            kinds.ignored.append(c)
        elif pd.api.types.is_bool_dtype(s):
            kinds.categorical.append(c)
        elif pd.api.types.is_datetime64_any_dtype(s):
            kinds.temporal.append(c)
        elif pd.api.types.is_numeric_dtype(s):
            is_id = pd.api.types.is_integer_dtype(s) and n > 50 and nun > 0.95 * n
            (kinds.ignored if is_id else kinds.numeric).append(c)
        elif _looks_like_date(s):
            kinds.temporal.append(c)
        elif 2 <= nun <= MAX_DIM_CARDINALITY:
            kinds.categorical.append(c)
        else:
            kinds.ignored.append(c)
    return kinds


def prepare_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, ColumnKinds]:
    """Classe les colonnes et convertit les colonnes temporelles en datetime."""
    kinds = classify_columns(df)
    out = df.copy()
    for c in kinds.temporal:
        out[c] = pd.to_datetime(out[c], errors="coerce")
    return out, kinds


def apply_filters(
    df: pd.DataFrame,
    categorical: dict[str, list] | None = None,
    dates: dict[str, tuple] | None = None,
) -> pd.DataFrame:
    mask = pd.Series(True, index=df.index)
    for col, values in (categorical or {}).items():
        if values:
            mask &= df[col].notna() & df[col].astype(str).isin(values)
    for col, (start, end) in (dates or {}).items():
        mask &= df[col] >= pd.Timestamp(start)
        mask &= df[col] < pd.Timestamp(end) + pd.Timedelta(days=1)  # fin incluse
    return df[mask]


def build_dashboard(df: pd.DataFrame, kinds: ColumnKinds) -> Dashboard:
    """Version DataFrame : enregistre `df` dans DuckDB puis réutilise build_dashboard_sql."""
    con = duckdb.connect()
    try:
        con.register("data", df)
        return build_dashboard_sql(con, kinds)
    finally:
        con.close()
