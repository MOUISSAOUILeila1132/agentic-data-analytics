import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

CSV = b"id,montant,categorie\n1,10,A\n2,20,A\n3,15,B\n4,1000,B\n4,1000,B\n"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    client = TestClient(app)
    ds_id = client.post("/datasets", files={"file": ("v.csv", CSV, "text/csv")}).json()["id"]
    return client, ds_id


def q(ctx, sql, **kw):
    client, ds_id = ctx
    return client.post(f"/datasets/{ds_id}/query", json={"sql": sql, **kw})


def test_valid_aggregation_matches_reference(ctx):
    r = q(ctx, "SELECT categorie, SUM(montant) AS total FROM data GROUP BY categorie ORDER BY categorie")
    assert r.status_code == 200
    assert r.json()["rows"] == [["A", 30], ["B", 2015]]


@pytest.mark.parametrize("sql", [
    "DROP TABLE data",
    "DELETE FROM data",
    "UPDATE data SET montant = 0",
    "CREATE TABLE x AS SELECT 1",
    "SELECT 1; DROP TABLE data",
    "COPY data TO 'out.csv'",
    "ATTACH 'x.db'",
    "PRAGMA database_list",
    "INSTALL httpfs",
    "SELECT * FROM read_csv('C:/Windows/win.ini')",
    "SELECT * FROM glob('*')",
    "",
])
def test_forbidden_queries_are_rejected(ctx, sql):
    assert q(ctx, sql).status_code == 400


def test_row_limit_and_truncation(ctx):
    r = q(ctx, "SELECT * FROM data", max_rows=2).json()
    assert r["row_count"] == 2 and r["truncated"] is True


def test_timeout(ctx, monkeypatch):
    monkeypatch.setattr(settings, "query_timeout_s", 1)
    r = q(ctx, "SELECT sum(hash(a.range + b.range)) FROM range(100000) a, range(100000) b")
    assert r.status_code == 408