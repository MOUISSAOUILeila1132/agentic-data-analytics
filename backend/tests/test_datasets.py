import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return TestClient(app)


CSV = b"id,montant,categorie\n1,10,A\n2,20,A\n3,15,B\n4,1000,B\n4,1000,B\n"


def test_upload_profile_preview(client):
    r = client.post("/datasets", files={"file": ("ventes.csv", CSV, "text/csv")})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    p = client.get(f"/datasets/{ds_id}/profile").json()
    assert p["rows"] == 5 and p["duplicate_rows"] == 1
    assert client.get(f"/datasets/{ds_id}/preview").json()["columns"] == ["id", "montant", "categorie"]


def test_rejects_invalid_files(client):
    assert client.post("/datasets", files={"file": ("x.exe", b"abc")}).status_code == 400
    assert client.post("/datasets", files={"file": ("vide.csv", b"")}).status_code == 400