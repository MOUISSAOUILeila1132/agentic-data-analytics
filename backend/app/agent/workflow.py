"""Agent d'analyse, étape 2 : workflow LangGraph.

Même contrat que `sql_agent.ask` (mêmes entrées, même dictionnaire de sortie) : l'API et le
frontend ne changent pas. Les prompts et helpers restent dans `sql_agent.py`.

Graphe (cahier des charges, §6.2) :

    build_context ─► plan ─┬─► execute ─► verify ─┬─► explain ─► check_answer ─┬─► finish_answer
    (Data Context)  (Query │  (Execution  (Verification  (Response           │   (Verification
                    Underst│   Layer)      Layer)         Generator)         │    de la réponse)
                    + Plan)│        ▲           │                ▲           │
                           │        └─ échec ───┘                └─ chiffres ┘
                           ├─► finish_plain   (clarification / impossible / erreur / résultat vide)
                           └─► plan           (nouvelle tentative contrôlée, MAX_ATTEMPTS)

Principe : le LLM planifie et rédige, le code exécute et vérifie.
"""
import json
import math
import operator
import re
from typing import Annotated, TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph

from app.agent.sql_agent import (
    MAX_ATTEMPTS,
    MAX_QUESTION_LENGTH,
    ROWS_FOR_EXPLANATION,
    SYSTEM_EXPLAIN,
    SYSTEM_SQL,
    _extract_json,
    _payload,
    _sql_prompt,
)
from app.agent.mcp_client import get_data_context, run_sql_query
from app.services.llm_client import complete

MAX_EXPLAIN_ATTEMPTS = 2  # 1 rédaction + 1 correction si des chiffres ne sont pas dans le résultat

ERROR_ANSWER = "Je n'ai pas réussi à produire une requête valide pour cette question. Essaie de la reformuler."
EMPTY_ANSWER = (
    "La requête s'est exécutée correctement mais ne renvoie aucune ligne : "
    "aucune donnée ne correspond à cette question."
)
LLM_DOWN_ANSWER = "Voici le résultat de l'analyse (l'explication automatique est indisponible pour le moment)."
UNVERIFIED_ANSWER = (
    "Voici le résultat de l'analyse. L'explication automatique n'a pas pu être vérifiée "
    "par rapport aux données : appuie-toi sur le tableau détaillé."
)


# ------------------------------------------------------------------ état du graphe
class AgentState(TypedDict, total=False):
    # entrées
    dataset_id: str
    question: str
    history: list[dict]
    # état de travail
    context: str
    attempt: int
    feedback: str | None
    plan_status: str  # sql | clarification | impossible | retry | failed
    sql: str | None
    result: dict | None
    exec_ok: bool
    verdict: str  # ok | empty | retry
    answer: str
    explain_attempt: int
    explain_feedback: str | None
    explain_skip: bool
    grounded: bool
    terminal: dict | None  # réponse sans passer par l'explication
    steps: Annotated[list[dict], operator.add]  # trace (Langfuse plus tard)
    # sortie
    output: dict


# ------------------------------------------------------------------ vérification numérique
_NUM_RE = re.compile(r"\d{1,3}(?:[\u00a0\u202f ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


def _parse_numbers(text: str) -> list[tuple[float, int, str]]:
    """Nombres d'un texte : (valeur, nb de décimales, texte d'origine). Gère « 1 921 996,25 »."""
    found = []
    for m in _NUM_RE.finditer(str(text)):
        raw = re.sub(r"[\u00a0\u202f ]", "", m.group())
        decimals = 0
        if re.search(r"[.,]\d+$", raw):
            decimals = len(re.split(r"[.,]", raw)[-1])
            raw = raw.replace(",", ".")
        try:
            found.append((float(raw), decimals, m.group().strip()))
        except ValueError:
            continue
    return found


def _row_values(row):
    return list(row.values()) if isinstance(row, dict) else list(row)


def _is_null(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def _column_totals(result: dict) -> dict[str, float]:
    """Somme de chaque colonne numérique, calculée par le code (jamais par le LLM).

    Vide si le résultat est tronqué (le total serait faux)."""
    if result["truncated"]:
        return {}
    totals = {}
    for j, col in enumerate(result["columns"]):
        vals = []
        for row in result["rows"]:
            v = row.get(col) if isinstance(row, dict) else row[j]
            if isinstance(v, bool) or _is_null(v) or not isinstance(v, (int, float)):
                continue
            vals.append(float(v))
        if vals:
            totals[col] = round(math.fsum(vals), 2)
    return totals


def _allowed_numbers(question: str, result: dict) -> list[float]:
    """Nombres que la réponse a le droit de citer : ceux que le LLM a reçus + les rangs."""
    shown = result["rows"][:ROWS_FOR_EXPLANATION]
    allowed = [0.0, float(result["row_count"]), float(len(result["columns"]))]
    allowed += [float(i) for i in range(1, len(shown) + 1)]  # « 1. Laptop, 2. Bureau… »
    for text in (question, result.get("sql") or ""):
        allowed += [v for v, _, _ in _parse_numbers(text)]
    for row in shown:
        for v in _row_values(row):
            if isinstance(v, bool) or _is_null(v):
                continue
            if isinstance(v, (int, float)):
                allowed.append(float(v))
            else:
                allowed += [x for x, _, _ in _parse_numbers(str(v))]
    allowed += list(_column_totals(result).values())  # totaux fournis (et vérifiés) par le code
    return allowed


def _matches(x: float, decimals: int, allowed: list[float]) -> bool:
    for v in allowed:
        if decimals == 0:
            if x in (v, round(v), math.floor(v)):
                return True
        elif round(v, decimals) == round(x, decimals):
            return True
    return False


def ungrounded_numbers(answer: str, question: str, result: dict) -> list[str]:
    """Chiffres de la réponse absents du résultat (donc potentiellement inventés ou recalculés)."""
    allowed = _allowed_numbers(question, result)
    return [raw for x, d, raw in _parse_numbers(answer) if not _matches(x, d, allowed)]


# ------------------------------------------------------------------ nœuds
def build_context_node(state: AgentState) -> dict:
    """Data Context Builder : schéma, valeurs manquantes, modalités, exemples."""
    return {
        "context": get_data_context(state["dataset_id"]),  # via le serveur MCP
        "steps": [{"node": "build_context", "step": "context", "ok": True}],
    }


def _retry_or_fail(attempt: int, feedback: str, step: dict) -> dict:
    update = {"attempt": attempt, "feedback": feedback, "steps": [step]}
    if attempt >= MAX_ATTEMPTS:
        update.update(plan_status="failed", terminal={"status": "error", "answer": ERROR_ANSWER})
    else:
        update["plan_status"] = "retry"
    return update


def plan_node(state: AgentState) -> dict:
    """Query Understanding + Planner : le LLM choisit entre SQL, clarification ou « impossible »."""
    attempt = state.get("attempt", 0) + 1
    raw = complete(
        SYSTEM_SQL,
        _sql_prompt(state["context"], state["question"], state.get("history"), state.get("feedback")),
        max_tokens=800,
    )
    base = {"node": "plan", "attempt": attempt}

    try:
        plan = _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        return _retry_or_fail(
            attempt,
            "Ta réponse précédente n'était pas un JSON valide. Réponds uniquement avec l'objet JSON demandé.",
            {**base, "step": "parse", "ok": False},
        )

    status = plan.get("status")
    message = str(plan.get("message") or "").strip()

    if status == "clarification":
        return {
            "attempt": attempt, "plan_status": "clarification", "sql": None,
            "terminal": {"status": "clarification", "answer": message or "Peux-tu préciser ta question ?"},
            "steps": [{**base, "step": "clarification", "ok": True}],
        }
    if status == "impossible":
        return {
            "attempt": attempt, "plan_status": "impossible", "sql": None,
            "terminal": {
                "status": "impossible",
                "answer": message or "Les données disponibles ne permettent pas de répondre à cette question.",
            },
            "steps": [{**base, "step": "impossible", "ok": True}],
        }

    sql = str(plan.get("sql") or "").strip()
    if status != "sql" or not sql:
        return _retry_or_fail(
            attempt,
            'Réponse invalide : utilise status "sql", "clarification" ou "impossible", '
            'avec un champ "sql" non vide pour "sql".',
            {**base, "step": "plan", "ok": False},
        )
    return {
        "attempt": attempt, "plan_status": "sql", "sql": sql, "feedback": None,
        "steps": [{**base, "step": "plan", "ok": True, "sql": sql}],
    }


def execute_node(state: AgentState) -> dict:
    """Execution Layer : validation SQL + exécution en lecture seule (sql_engine)."""
    sql, attempt = state["sql"], state["attempt"]
    base = {"node": "execute", "attempt": attempt}
    try:
        result = run_sql_query(state["dataset_id"], sql)  # via le serveur MCP
    except HTTPException as e:
        if e.status_code not in (400, 408):  # SQL invalide / interdit / trop lent : on réessaie
            raise
        update = {
            "result": None, "exec_ok": False,
            "feedback": (
                f"La requête suivante a échoué.\nSQL : {sql}\nErreur : {e.detail}\n"
                "Corrige-la (ou simplifie-la) en respectant les règles."
            ),
            "steps": [{**base, "step": "execute", "ok": False, "sql": sql, "error": str(e.detail)}],
        }
        if attempt >= MAX_ATTEMPTS:
            update["terminal"] = {"status": "error", "answer": ERROR_ANSWER}
        return update
    return {
        "result": result, "exec_ok": True, "feedback": None,
        "steps": [{**base, "step": "execute", "ok": True, "sql": sql, "elapsed_ms": result["elapsed_ms"]}],
    }


def verify_node(state: AgentState) -> dict:
    """Verification Layer (résultat) : vide ? entièrement NULL ?"""
    result, attempt = state["result"], state["attempt"]
    base = {"node": "verify", "attempt": attempt, "step": "verify"}

    if result["row_count"] == 0:
        return {
            "verdict": "empty",
            "terminal": {"status": "ok", "answer": EMPTY_ANSWER},
            "steps": [{**base, "ok": True, "verdict": "empty"}],
        }

    all_null = all(_is_null(v) for row in result["rows"] for v in _row_values(row))
    if all_null and attempt < MAX_ATTEMPTS:
        return {
            "verdict": "retry", "result": None,
            "feedback": (
                f"La requête a renvoyé uniquement des valeurs NULL.\nSQL : {state['sql']}\n"
                "Vérifie les colonnes, les filtres et l'agrégation, puis corrige-la."
            ),
            "steps": [{**base, "ok": False, "verdict": "all_null"}],
        }
    return {"verdict": "ok", "steps": [{**base, "ok": True, "verdict": "ok"}]}


def explain_node(state: AgentState) -> dict:
    """Response Generator : le LLM rédige à partir du résultat déjà calculé."""
    result, n = state["result"], state.get("explain_attempt", 0) + 1
    content = {
        "colonnes": result["columns"],
        "lignes": result["rows"][:ROWS_FOR_EXPLANATION],
        "nombre_lignes": result["row_count"],
        "resultat_tronque": result["truncated"],
    }
    totals = _column_totals(result)
    if totals:
        content["totaux_colonnes"] = totals  # calculés par le code
    payload = json.dumps(content, ensure_ascii=False, default=str)
    user = f"Question : {state['question']}\nSQL exécuté : {result['sql']}\nRésultat (JSON) : {payload}"
    if totals:
        user += (
            "\nSi tu cites un total général, utilise uniquement `totaux_colonnes`, et seulement si la mesure "
            "est additive (somme ou nombre) : jamais pour une moyenne ou un ratio."
        )
    if state.get("explain_feedback"):
        user += "\n" + state["explain_feedback"]
    base = {"node": "explain", "attempt": n, "step": "explain"}
    try:
        answer = complete(SYSTEM_EXPLAIN, user, max_tokens=600).strip()
    except HTTPException:
        # Le résultat calculé reste valable même si l'explication échoue.
        return {
            "answer": LLM_DOWN_ANSWER, "explain_attempt": n, "explain_skip": True,
            "steps": [{**base, "ok": False, "error": "llm_unavailable"}],
        }
    return {"answer": answer, "explain_attempt": n, "steps": [{**base, "ok": True}]}


def _salvage(answer: str, question: str, result: dict) -> str:
    """Garde uniquement les phrases dont tous les chiffres sont vérifiés ; sinon texte neutre."""
    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    kept = [s for s in sentences if not ungrounded_numbers(s, question, result)]
    return " ".join(kept) if kept else UNVERIFIED_ANSWER


def check_answer_node(state: AgentState) -> dict:
    """Verification Layer (réponse) : tout chiffre cité doit venir du résultat."""
    base = {"node": "check_answer", "attempt": state["explain_attempt"], "step": "grounding"}
    if state.get("explain_skip"):
        return {"grounded": True, "steps": [{**base, "ok": True, "skipped": True}]}

    bad = ungrounded_numbers(state["answer"], state["question"], state["result"])
    if not bad:
        return {"grounded": True, "steps": [{**base, "ok": True}]}

    step = {**base, "ok": False, "ungrounded": bad}
    if state["explain_attempt"] < MAX_EXPLAIN_ATTEMPTS:
        return {
            "grounded": False,
            "explain_feedback": (
                "Ta réponse précédente contient des chiffres absents du résultat : "
                + ", ".join(bad)
                + ". Réécris-la en utilisant uniquement les valeurs du résultat, sans rien recalculer."
            ),
            "steps": [step],
        }
    # Dernier recours : on ne présente jamais un chiffre non vérifié (phrases fautives retirées).
    cleaned = _salvage(state["answer"], state["question"], state["result"])
    return {
        "grounded": True,
        "answer": cleaned,
        "steps": [{**step, "salvaged": cleaned != UNVERIFIED_ANSWER}],
    }


def finish_plain_node(state: AgentState) -> dict:
    """Sortie sans explication : clarification, impossible, erreur ou résultat vide."""
    t, result = state["terminal"], state.get("result")
    sql = result["sql"] if result else state.get("sql")
    return {"output": _payload(t["status"], t["answer"], sql, result, state["attempt"], state["steps"])}


def finish_answer_node(state: AgentState) -> dict:
    result = state["result"]
    return {"output": _payload("ok", state["answer"], result["sql"], result, state["attempt"], state["steps"])}


# ------------------------------------------------------------------ routage
def route_after_plan(state: AgentState) -> str:
    return {"sql": "execute", "retry": "plan"}.get(state["plan_status"], "finish_plain")


def route_after_execute(state: AgentState) -> str:
    if state["exec_ok"]:
        return "verify"
    return "finish_plain" if state["attempt"] >= MAX_ATTEMPTS else "plan"


def route_after_verify(state: AgentState) -> str:
    return {"ok": "explain", "retry": "plan"}.get(state["verdict"], "finish_plain")


def route_after_check(state: AgentState) -> str:
    return "finish_answer" if state["grounded"] else "explain"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("build_context", build_context_node)
    g.add_node("plan", plan_node)
    g.add_node("execute", execute_node)
    g.add_node("verify", verify_node)
    g.add_node("explain", explain_node)
    g.add_node("check_answer", check_answer_node)
    g.add_node("finish_plain", finish_plain_node)
    g.add_node("finish_answer", finish_answer_node)

    g.add_edge(START, "build_context")
    g.add_edge("build_context", "plan")
    g.add_conditional_edges("plan", route_after_plan, ["execute", "plan", "finish_plain"])
    g.add_conditional_edges("execute", route_after_execute, ["verify", "plan", "finish_plain"])
    g.add_conditional_edges("verify", route_after_verify, ["explain", "plan", "finish_plain"])
    g.add_edge("explain", "check_answer")
    g.add_conditional_edges("check_answer", route_after_check, ["finish_answer", "explain"])
    g.add_edge("finish_plain", END)
    g.add_edge("finish_answer", END)
    return g.compile()


GRAPH = build_graph()


# ------------------------------------------------------------------ point d'entrée
def ask(dataset_id: str, question: str, history: list[dict] | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        raise HTTPException(400, "Question vide.")
    if len(question) > MAX_QUESTION_LENGTH:
        raise HTTPException(400, "Question trop longue.")

    final = GRAPH.invoke(
        {
            "dataset_id": dataset_id,
            "question": question,
            "history": history or [],
            "attempt": 0,
            "steps": [],
        },
        config={"recursion_limit": 40},
    )
    return final["output"]
