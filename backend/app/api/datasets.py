import logging

from fastapi import APIRouter, BackgroundTasks, File, UploadFile

from app.core.config import settings
from app.services import dataset_service as ds
from app.services.context_service import build_schema_context
from app.services.profiling_service import get_profile

log = logging.getLogger("datasets")
router = APIRouter(prefix="/datasets", tags=["datasets"])


def _warm_caches(dataset_id: str) -> None:
    """Pré-calcule le profil et le contexte LLM après l'upload : 1re question / 1er dashboard instantanés."""
    try:
        get_profile(dataset_id)
        build_schema_context(dataset_id)
    except Exception:  # noqa: BLE001 : le calcul sera refait à la demande
        log.exception("Pré-calcul impossible pour le dataset %s", dataset_id)


@router.post("", status_code=201)
def upload_dataset(background: BackgroundTasks, file: UploadFile = File(...)):
    # `def` (et non `async def`) : FastAPI l'exécute dans un thread, donc la conversion
    # CSV -> Parquet, qui peut durer, ne bloque pas le serveur.
    meta = ds.ingest_upload(file)
    background.add_task(_warm_caches, meta["id"])  # après la réponse : l'upload reste rapide
    return meta


@router.get("")
def list_datasets():
    return ds.list_datasets()


@router.get("/{dataset_id}/preview")
def preview(dataset_id: str, rows: int = settings.preview_rows):
    rows = max(1, min(rows, 100))
    return ds.preview_dataset(dataset_id, rows)


@router.get("/{dataset_id}/profile")
def profile(dataset_id: str):
    return get_profile(dataset_id)  # calculé par DuckDB, puis mis en cache (profile.json)


@router.delete("/{dataset_id}", status_code=204)
def delete(dataset_id: str):
    ds.delete_dataset(dataset_id)
