import io
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import HTTPException, UploadFile

from app.core.config import settings


# --------------------------------------------------------------------------- #
# Chemins et connexion DuckDB
# --------------------------------------------------------------------------- #
def dataset_dir(dataset_id: str) -> Path:
    try:
        uuid.UUID(dataset_id)  # empêche le path traversal
    except ValueError:
        raise HTTPException(404, "Dataset introuvable.")
    path = settings.data_dir / dataset_id
    if not path.exists():
        raise HTTPException(404, "Dataset introuvable.")
    return path


def parquet_path(dataset_id: str) -> Path:
    """Chemin absolu du Parquet du dataset (absolu : nécessaire pour allowed_paths)."""
    return (dataset_dir(dataset_id) / "data.parquet").resolve()


def sql_str(value) -> str:
    """Échappe un chemin / texte pour l'insérer dans un littéral SQL '...'."""
    text = value.as_posix() if isinstance(value, Path) else str(value)
    return text.replace("'", "''")


def _q(identifier: str) -> str:
    """Quote un identifiant SQL."""
    return '"' + str(identifier).replace('"', '""') + '"'


def open_connection(dataset_id: str, view_name: str = "data") -> duckdb.DuckDBPyConnection:
    """Connexion DuckDB en mémoire avec la vue `data` (ou `view_name`) posée sur le Parquet.

    Aucune copie en RAM : DuckDB lit seulement les colonnes et les blocs utiles.
    Si la mémoire ne suffit pas, il déborde sur disque (temp_directory).
    """
    parquet = sql_str(parquet_path(dataset_id))
    tmp_dir = (settings.data_dir / ".duckdb_tmp").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(":memory:")
    con.execute(f"SET memory_limit='{sql_str(settings.duckdb_memory_limit)}'")
    con.execute(f"SET threads={int(settings.duckdb_threads)}")
    con.execute(f"SET temp_directory='{sql_str(tmp_dir)}'")
    con.execute(f"CREATE VIEW {_q(view_name)} AS SELECT * FROM read_parquet('{parquet}')")
    return con


# --------------------------------------------------------------------------- #
# Ingestion en streaming (CSV / Parquet -> Parquet via DuckDB)
# --------------------------------------------------------------------------- #
# Tentatives successives de lecture d'un CSV : encodage, puis tout en texte si
# la détection de types échoue sur une ligne tardive.
_CSV_ATTEMPTS = (
    "",
    "encoding='latin-1'",
    "all_varchar=true",
    "all_varchar=true, encoding='latin-1'",
)


def _stream_to_disk(file: UploadFile, dest: Path, max_bytes: int, max_mb: int) -> int:
    """Copie l'upload sur disque par blocs, sans jamais le charger en entier en RAM."""
    chunk = max(1, settings.upload_chunk_mb) * 1024 * 1024
    written = 0
    with open(dest, "wb") as out:
        while True:
            block = file.file.read(chunk)
            if not block:
                break
            written += len(block)
            if written > max_bytes:
                raise HTTPException(413, f"Fichier trop volumineux (max {max_mb} Mo).")
            out.write(block)
    return written


def _clean_select(con: duckdb.DuckDBPyConnection, source: str) -> str:
    """SELECT qui nettoie les noms de colonnes (strip, vides, doublons)."""
    names = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()]
    used: set[str] = set()
    parts = []
    for i, original in enumerate(names, start=1):
        base = str(original).strip() or f"colonne_{i}"
        final, k = base, 2
        while final.lower() in used:
            final = f"{base}_{k}"
            k += 1
        used.add(final.lower())
        parts.append(f"{_q(original)} AS {_q(final)}")
    return ", ".join(parts)


def _convert_to_parquet(src: Path, ext: str, dest: Path) -> None:
    """Convertit un CSV ou un Parquet en Parquet compressé (ZSTD), en streaming."""
    src_sql, dest_sql = sql_str(src.resolve()), sql_str(dest.resolve())
    tmp_dir = (settings.data_dir / ".duckdb_tmp").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)

    attempts = _CSV_ATTEMPTS if ext == ".csv" else ("",)
    last_error: Exception | None = None
    for options in attempts:
        con = duckdb.connect(":memory:")
        try:
            con.execute(f"SET memory_limit='{sql_str(settings.duckdb_memory_limit)}'")
            con.execute(f"SET threads={int(settings.duckdb_threads)}")
            con.execute(f"SET temp_directory='{sql_str(tmp_dir)}'")
            if ext == ".csv":
                extra = f", {options}" if options else ""
                source = f"read_csv('{src_sql}', sample_size=200000{extra})"
            else:
                source = f"read_parquet('{src_sql}')"
            select = _clean_select(con, source)
            con.execute(
                f"COPY (SELECT {select} FROM {source}) TO '{dest_sql}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD)"
            )
            return
        except duckdb.Error as e:
            last_error = e
            dest.unlink(missing_ok=True)
        finally:
            con.close()
    raise HTTPException(400, "Fichier illisible ou corrompu.") from last_error


def _parquet_shape(path: Path) -> tuple[int, int]:
    con = duckdb.connect(":memory:")
    try:
        p = sql_str(path.resolve())
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0]
        cols = len(con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall())
        return int(rows), int(cols)
    finally:
        con.close()


def _write_df_parquet(df: pd.DataFrame, dest: Path) -> None:
    try:
        df.to_parquet(dest, index=False)
    except Exception:
        raise HTTPException(400, "Impossible de convertir ce fichier (types de colonnes mixtes ?).")


def ingest_upload(file: UploadFile) -> dict:
    """Upload -> disque (streaming) -> Parquet. Fonctionne pour de très gros fichiers.

    CSV / Parquet : jamais chargés en entier en mémoire (DuckDB lit et écrit par blocs).
    Excel : lu par pandas (limité par `max_excel_mb`).
    """
    filename = Path(file.filename or "dataset").name
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            400, f"Format non supporté ({ext or 'aucune extension'}). "
                 f"Formats acceptés : {', '.join(settings.allowed_extensions)}."
        )

    dataset_id = str(uuid.uuid4())
    folder = settings.data_dir / dataset_id
    folder.mkdir(parents=True)
    raw = folder / f"upload{ext}"
    parquet = folder / "data.parquet"

    try:
        limit_mb = settings.max_excel_mb if ext == ".xlsx" else settings.max_upload_mb
        size = _stream_to_disk(file, raw, limit_mb * 1024 * 1024, limit_mb)
        if size == 0:
            raise HTTPException(400, "Le fichier est vide.")

        if ext == ".xlsx":
            try:
                df = pd.read_excel(raw)
            except Exception:
                raise HTTPException(400, "Fichier illisible ou corrompu.")
            df.columns = [str(c).strip() for c in df.columns]
            _write_df_parquet(df, parquet)
        else:
            _convert_to_parquet(raw, ext, parquet)

        rows, cols = _parquet_shape(parquet)
        if rows == 0 or cols == 0:
            raise HTTPException(400, "Le fichier ne contient aucune donnée exploitable.")

        meta = {
            "id": dataset_id,
            "filename": filename,
            "rows": rows,
            "columns": cols,
            "size_bytes": size,
            "parquet_bytes": parquet.stat().st_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        raw.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Lecture
# --------------------------------------------------------------------------- #
def preview_dataset(dataset_id: str, rows: int) -> dict:
    """Aperçu : lit seulement les premières lignes (pas de chargement complet)."""
    con = open_connection(dataset_id)
    try:
        df = con.execute(f"SELECT * FROM data LIMIT {int(rows)}").df()
    finally:
        con.close()
    return {
        "columns": list(df.columns),
        "rows": json.loads(df.to_json(orient="records", date_format="iso")),
    }


def list_datasets() -> list[dict]:
    if not settings.data_dir.exists():
        return []
    metas = [json.loads(p.read_text(encoding="utf-8")) for p in settings.data_dir.glob("*/meta.json")]
    return sorted(metas, key=lambda m: m["created_at"], reverse=True)


def load_dataframe(dataset_id: str, limit: int | None = None) -> pd.DataFrame:
    """⚠ Charge en mémoire. À réserver aux petits datasets ou avec `limit`.

    Conservé pour compatibilité ; préférer open_connection() + SQL pour tout calcul.
    """
    path = parquet_path(dataset_id)
    if limit is None:
        return pd.read_parquet(path)
    con = duckdb.connect(":memory:")
    try:
        return con.execute(f"SELECT * FROM read_parquet('{sql_str(path)}') LIMIT {int(limit)}").df()
    finally:
        con.close()


def delete_dataset(dataset_id: str) -> None:
    shutil.rmtree(dataset_dir(dataset_id))


# --------------------------------------------------------------------------- #
# Anciennes fonctions (compatibilité : tests / petits fichiers en mémoire)
# --------------------------------------------------------------------------- #
def read_upload(content: bytes, filename: str) -> pd.DataFrame:
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            400, f"Format non supporté ({ext or 'aucune extension'}). "
                 f"Formats acceptés : {', '.join(settings.allowed_extensions)}."
        )
    if not content:
        raise HTTPException(400, "Le fichier est vide.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Fichier trop volumineux (max {settings.max_upload_mb} Mo).")

    try:
        if ext == ".csv":
            try:
                df = pd.read_csv(io.BytesIO(content), sep=None, engine="python")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(content), sep=None, engine="python", encoding="latin-1")
        elif ext == ".xlsx":
            df = pd.read_excel(io.BytesIO(content))
        else:
            df = pd.read_parquet(io.BytesIO(content))
    except Exception:
        raise HTTPException(400, "Fichier illisible ou corrompu.")

    if df.empty or df.shape[1] == 0:
        raise HTTPException(400, "Le fichier ne contient aucune donnée exploitable.")
    df.columns = [str(c).strip() for c in df.columns]
    return df


def save_dataset(df: pd.DataFrame, filename: str) -> dict:
    dataset_id = str(uuid.uuid4())
    folder = settings.data_dir / dataset_id
    folder.mkdir(parents=True)
    try:
        _write_df_parquet(df, folder / "data.parquet")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    meta = {
        "id": dataset_id,
        "filename": Path(filename).name,
        "rows": int(df.shape[0]),
        "columns": int(df.shape[1]),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return meta
