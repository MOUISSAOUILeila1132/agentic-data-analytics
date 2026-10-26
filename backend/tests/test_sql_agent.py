import json

import pytest
from fastapi import HTTPException

from app.agent import sql_agent

OK_RESULT = {
    "sql": "SELECT region, SUM(montant) AS total FROM data GROUP BY region",
    "columns": ["region", "total"],
    "rows": [["Tunis", 100.0], ["Sfax", 50.0]],
    "row_count": 2,
    "truncated": False,
    "elapsed_ms": 1.0,
}


def _sql_reply(sql):
    return json.dumps({"status": "sql", "sql": sql, "message": ""})


def _setup(monkeypatch, llm_replies, query):
    replies = iter(llm_replies)
    monkeypatch.setattr(sql_agent, "build_schema_context", lambda _id: "ctx")
    monkeypatch.setattr(sql_agent, "complete", lambda *a, **k: next(replies))
    monkeypatch.setattr(sql_agent, "run_readonly_query", query)


def test_happy_path(monkeypatch):
    _setup(monkeypatch, [_sql_reply(OK_RESULT["sql"]), "Tunis réalise le plus de ventes."], lambda *_: OK_RESULT)
    out = sql_agent.ask("d1", "Ventes par région ?")
    assert out["status"] == "ok"
    assert out["sql"] == OK_RESULT["sql"]
    assert out["row_count"] == 2
    assert out["attempts"] == 1


def test_retry_after_sql_error(monkeypatch):
    calls = {"n": 0}

    def query(_id, _sql):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HTTPException(400, "Erreur d'exécution : colonne inconnue")
        return OK_RESULT

    _setup(monkeypatch, [_sql_reply("SELECT x FROM data"), _sql_reply(OK_RESULT["sql"]), "Réponse."], query)
    out = sql_agent.ask("d1", "Ventes par région ?")
    assert out["status"] == "ok"
    assert out["attempts"] == 2
    assert out["steps"][0]["ok"] is False


def test_gives_up_after_max_attempts(monkeypatch):
    def query(*_):
        raise HTTPException(400, "Mot-clé interdit : DROP.")

    _setup(monkeypatch, [_sql_reply("DROP TABLE data")] * sql_agent.MAX_ATTEMPTS, query)
    out = sql_agent.ask("d1", "Supprime tout")
    assert out["status"] == "error"
    assert out["attempts"] == sql_agent.MAX_ATTEMPTS


def test_clarification(monkeypatch):
    reply = json.dumps({"status": "clarification", "sql": "", "message": "Quelle période ?"})
    _setup(monkeypatch, [reply], lambda *_: pytest.fail("ne doit pas exécuter de SQL"))
    out = sql_agent.ask("d1", "Combien ?")
    assert out["status"] == "clarification"
    assert out["answer"] == "Quelle période ?"


def test_impossible(monkeypatch):
    reply = json.dumps({"status": "impossible", "sql": "", "message": "Pas de colonne âge."})
    _setup(monkeypatch, [reply], lambda *_: pytest.fail("ne doit pas exécuter de SQL"))
    assert sql_agent.ask("d1", "Âge moyen ?")["status"] == "impossible"


def test_extract_json_tolerates_code_fence():
    raw = 'Voici :\n```json\n{"status": "sql", "sql": "SELECT 1", "message": ""}\n```'
    assert sql_agent._extract_json(raw)["sql"] == "SELECT 1"


def test_empty_question_rejected():
    with pytest.raises(HTTPException):
        sql_agent.ask("d1", "   ")
