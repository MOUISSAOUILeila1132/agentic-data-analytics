"""Charge utile du dashboard : filtres validés, options de filtres, KPI, widgets.

Utilisée par le serveur MCP (outil `get_dashboard`) ; la route API passe par le client MCP.
Gros datasets : le profil mis en cache classe les colonnes, puis tout est calculé en SQL sur le
Parquet (filtres inclus, dans la clause WHERE). Aucun DataFrame complet n'est chargé.
"""
import json
from datetime import date

import pandas as pd
from fastapi import HTTPException

from app.services.dashboard_service import (
    _q,
    as_date,
    build_dashboard_sql,
    classify_from_profile,
    prepare_view,
    text_expr,
)
from app.services.dataset_service import open_connection
from app.services.profiling_service import get_profile

MAX_FILTER_OPTIONS = 200  # valeurs proposées par filtre (les colonnes catégorielles sont déjà plafonnées)
MAX_FILTER_VALUES = 500   # valeurs cochées acceptées par filtre
MAX_TABLE_ROWS = 100      # lignes renvoyées par widget pour l'expander « Détails »
COMPACT_TABLE_ROWS = 20   # mode compact (LLM) : moins de lignes par widget


def _records(df: pd.DataFrame, limit: int) -> list[dict]:
    return json.loads(df.head(limit).to_json(orient="records", date_format="iso"))


def _lit(value) -> str:
    """Littéral SQL texte (apostrophes doublées)."""
    return "'" + str(value).replace("'", "''") + "'"


def compute_dashboard(
    dataset_id: str,
    categorical: dict[str, list[str]] | None = None,
    dates: dict[str, list[str]] | None = None,
    include_figures: bool = True,
) -> dict:
    """Construit le dashboard d'un dataset.

    include_figures=True  : mode complet (Streamlit) avec `figure_json` Plotly par widget.
    include_figures=False : mode compact (agent/LLM) sans figures, avec moins de lignes par widget.
    """
    categorical = categorical or {}
    dates = dates or {}
    kinds = classify_from_profile(get_profile(dataset_id))

    # ---- validation des filtres : seules les colonnes détectées comme catégorielles / temporelles
    unknown = [c for c in categorical if c not in kinds.categorical]
    unknown += [c for c in dates if c not in kinds.temporal]
    if unknown:
        raise HTTPException(400, f"Colonnes de filtre invalides : {', '.join(unknown)}.")
    if any(len(v or []) > MAX_FILTER_VALUES for v in categorical.values()):
        raise HTTPException(400, f"Trop de valeurs dans un filtre (max {MAX_FILTER_VALUES}).")

    parsed_dates: dict[str, tuple[date, date]] = {}
    for col, bounds in dates.items():
        try:
            start, end = (date.fromisoformat(b) for b in bounds)
        except (ValueError, TypeError):
            raise HTTPException(400, f"Plage de dates invalide pour « {col} » (attendu : [début, fin] ISO).")
        parsed_dates[col] = (start, end)

    con = open_connection(dataset_id, view_name="raw")
    try:
        prepare_view(con, kinds, source="raw")  # vue `data` (dates texte converties)

        # ---- filtres -> conditions SQL (valeurs échappées, dates reconstruites depuis des date ISO)
        conds: list[str] = []
        for col, values in categorical.items():
            if values:
                q, txt = _q(col), text_expr(kinds, col)
                conds.append(f"({q} IS NOT NULL AND {txt} IN ({', '.join(_lit(v) for v in values)}))")
        for col, (start, end) in parsed_dates.items():
            q = _q(col)
            lo, hi = con.execute(f"SELECT min({q}), max({q}) FROM data").fetchone()
            if lo is None:
                continue
            if start <= as_date(lo) and end >= as_date(hi):
                continue  # plage complète : pas de filtre (sinon les lignes sans date seraient exclues)
            conds.append(
                f"({q} >= TIMESTAMP '{start.isoformat()} 00:00:00' "
                f"AND {q} < TIMESTAMP '{end.isoformat()} 00:00:00' + INTERVAL 1 DAY)"
            )

        # ---- options de filtres (calculées sur les données non filtrées)
        filter_options = {"categorical": {}, "temporal": {}}
        for c in kinds.categorical:
            q = _q(c)
            rows = con.execute(
                f"SELECT DISTINCT {text_expr(kinds, c)} AS v FROM data WHERE {q} IS NOT NULL "
                f"ORDER BY v LIMIT {MAX_FILTER_OPTIONS}"
            ).fetchall()
            filter_options["categorical"][c] = [r[0] for r in rows]
        for c in kinds.temporal[:1]:
            lo, hi = con.execute(f"SELECT min({_q(c)}), max({_q(c)}) FROM data").fetchone()
            if lo is not None:
                filter_options["temporal"][c] = {
                    "min": as_date(lo).isoformat(),
                    "max": as_date(hi).isoformat(),
                }

        dash = build_dashboard_sql(con, kinds, conds)
    finally:
        con.close()

    limit = MAX_TABLE_ROWS if include_figures else COMPACT_TABLE_ROWS
    widgets = []
    for w in dash.widgets:
        item = {
            "id": w.id,
            "title": w.title,
            "kind": w.kind,
            "sql": w.sql,
            "columns": [str(c) for c in w.data.columns],
            "rows": _records(w.data, limit),
            "row_count": int(len(w.data)),
        }
        if include_figures:
            # chaîne JSON Plotly : le frontend la relit avec plotly.io.from_json
            item["figure_json"] = w.figure.to_json()
        widgets.append(item)

    return {
        "measure": dash.measure,
        "row_count": dash.rows,
        "kpis": [{"label": label, "value": value} for label, value in dash.kpis],
        "warnings": dash.warnings,
        "filter_options": filter_options,
        "widgets": widgets,
    }
