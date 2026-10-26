from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.sql_engine import run_readonly_query

router = APIRouter(prefix="/datasets", tags=["query"])


class QueryRequest(BaseModel):
    sql: str
    max_rows: int | None = Field(default=None, ge=1)


@router.post("/{dataset_id}/query")
def query(dataset_id: str, body: QueryRequest):
    return run_readonly_query(dataset_id, body.sql, body.max_rows)