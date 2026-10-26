"""Description compacte de la table `data` destinée au LLM (schéma, manquants, modalités, exemples).

Utilisée par le serveur MCP (outil `get_data_context`) et par l'agent.
Gros datasets : tout vient du profil mis en cache (types, manquants, nombre de valeurs distinctes)
et de quelques requêtes ciblées sur le Parquet. Le texte final est lui-même mis en cache
(context.v1.txt) : il est donc construit une seule fois par dataset.
"""
import re
import uuid

from app.services.dataset_service import dataset_dir, open_connection
from app.services.profiling_service import get_profile

MAX_DISTINCT_VALUES = 12    # valeurs listées pour les colonnes texte peu variées
N_SAMPLE_ROWS = 3           # lignes d'exemple envoyées au LLM (mettre 0 pour n'envoyer aucune valeur)
MAX_DETAILED_COLUMNS = 80   # au-delà, les colonnes suivantes sont listées sans détail (prompt compact)
MAX_LISTED_COLUMNS = 400    # plafond de noms de colonnes listés sans détail
CONTEXT_VERSION = 1         # à incrémenter si le format du texte change (invalide le cache)


def _short(value, limit: int = 40) -> str:
    """Valeur compacte sur une ligne (limite aussi la surface d'injection de prompt)."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _build(dataset_id: str) -> str:
    profile = get_profile(dataset_id)  # mis en cache : types, manquants, valeurs distinctes
    columns = profile["columns"]
    con = open_connection(dataset_id)
    try:
        lines = [f"Table `data` : {profile['rows']} lignes. Colonnes :"]
        for col in columns[:MAX_DETAILED_COLUMNS]:
            q = _quote(col["name"])
            line = f"- {q} ({col['dtype']}), {col['missing']} valeurs manquantes"
            if col["dtype"] == "VARCHAR" and 1 <= col["unique"] <= MAX_DISTINCT_VALUES:
                values = con.execute(
                    f"SELECT DISTINCT {q} FROM data WHERE {q} IS NOT NULL ORDER BY 1 LIMIT {MAX_DISTINCT_VALUES + 1}"
                ).fetchall()
                if len(values) <= MAX_DISTINCT_VALUES:  # garde-fou si le décompte était estimé
                    line += " ; valeurs possibles : " + ", ".join(repr(_short(v[0])) for v in values)
            lines.append(line)

        rest = columns[MAX_DETAILED_COLUMNS:]
        if rest:
            listed = ", ".join(f"{_quote(c['name'])} ({c['dtype']})" for c in rest[:MAX_LISTED_COLUMNS])
            more = f" … et {len(rest) - MAX_LISTED_COLUMNS} autres" if len(rest) > MAX_LISTED_COLUMNS else ""
            lines.append(f"Autres colonnes (sans détail) : {listed}{more}")

        if N_SAMPLE_ROWS > 0:
            cursor = con.execute(f"SELECT * FROM data LIMIT {int(N_SAMPLE_ROWS)}")
            names = [d[0] for d in cursor.description]
            lines.append("Exemples de lignes :")
            for row in cursor.fetchall():
                shown = list(zip(names, row))[:MAX_DETAILED_COLUMNS]
                lines.append("  " + ", ".join(f"{n}={_short(v)}" for n, v in shown))
        return "\n".join(lines)
    finally:
        con.close()


def build_schema_context(dataset_id: str) -> str:
    """Décrit la table `data` pour le LLM : types, valeurs manquantes, modalités, exemples."""
    folder = dataset_dir(dataset_id)
    cache = folder / f"context.v{CONTEXT_VERSION}.txt"
    try:
        return cache.read_text(encoding="utf-8")
    except OSError:
        pass
    text = _build(dataset_id)
    tmp = folder / f"context.{uuid.uuid4().hex}.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(cache)  # écriture atomique
    return text
