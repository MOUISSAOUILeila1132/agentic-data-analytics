import math
import re
import threading
import time

import duckdb
from fastapi import HTTPException

from app.core.config import settings
from app.services.dataset_service import open_connection, parquet_path, sql_str

# Second filet de sécurité : mots-clés et fonctions interdits
FORBIDDEN = re.compile(
    r"\b(attach|detach|copy|export|import|install|load|pragma|call|create|drop|alter|"
    r"insert|update|delete|truncate|vacuum|checkpoint|read_csv|read_csv_auto|read_parquet|"
    r"parquet_scan|read_json|read_json_auto|read_text|read_blob|glob|sniff_csv|httpfs)\b",
    re.IGNORECASE,
)


def validate_sql(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    """Valide la requête : une seule instruction, de type SELECT, sans mot interdit."""
    sql = (sql or "").strip().rstrip(";").strip()
    if not sql:
        raise HTTPException(400, "Requête vide.")
    if len(sql) > settings.max_sql_length:
        raise HTTPException(400, "Requête trop longue.")

    # Couche 1 : parsing par DuckDB (nombre et type d'instructions)
    try:
        statements = con.extract_statements(sql)
    except duckdb.Error:
        raise HTTPException(400, "Requête SQL invalide (erreur de syntaxe).")
    if len(statements) != 1:
        raise HTTPException(400, "Une seule requête est autorisée.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise HTTPException(400, "Seules les requêtes SELECT sont autorisées.")

    # Couche 2 : mots interdits (hors contenu des chaînes de caractères)
    without_literals = re.sub(r"'(?:[^']|'')*'", "''", sql)
    match = FORBIDDEN.search(without_literals)
    if match:
        raise HTTPException(400, f"Mot-clé interdit : {match.group(1).upper()}.")
    return sql


def _clean(value):
    """Remplace NaN / inf par None pour que le JSON reste valide."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run_readonly_query(dataset_id: str, sql: str, max_rows: int | None = None) -> dict:
    """Exécute une requête SELECT sur le dataset (exposé comme vue `data`, sans copie en RAM)."""
    limit = min(max_rows or settings.max_result_rows, settings.max_result_rows)
    parquet = parquet_path(dataset_id)

    con = open_connection(dataset_id)  # vue `data` + limites mémoire / threads / disque
    try:
        clean_sql = validate_sql(con, sql)

        # Couche 3 : connexion verrouillée (seul le Parquet du dataset reste lisible, via la vue)
        con.execute(f"SET allowed_paths=['{sql_str(parquet)}']")
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")

        # Couche 4 : limite de temps
        timer = threading.Timer(settings.query_timeout_s, con.interrupt)
        timer.start()
        start = time.perf_counter()
        try:
            # LIMIT imposée par le moteur : un SELECT * sur 50 M de lignes ne sort jamais en entier
            cursor = con.execute(f"SELECT * FROM ({clean_sql}) AS q LIMIT {limit + 1}")
            columns = [d[0] for d in cursor.description]
            fetched = cursor.fetchall()
        except duckdb.InterruptException:
            raise HTTPException(
                408, f"Requête interrompue : durée maximale de {settings.query_timeout_s} s dépassée."
            )
        except duckdb.Error as e:
            raise HTTPException(400, f"Erreur d'exécution : {str(e)[:300]}")
        finally:
            timer.cancel()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    finally:
        con.close()

    truncated = len(fetched) > limit
    rows = [[_clean(v) for v in row] for row in fetched[:limit]]
    return {
        "sql": clean_sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "elapsed_ms": elapsed_ms,
    }
