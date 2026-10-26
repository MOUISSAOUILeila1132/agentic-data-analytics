from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agent.workflow import ask

router = APIRouter(prefix="/agent", tags=["agent"])


class HistoryItem(BaseModel):
    question: str = Field(max_length=1000)
    sql: str | None = Field(default=None, max_length=5000)


class AskRequest(BaseModel):
    dataset_id: str
    question: str = Field(min_length=1, max_length=1000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=10)


@router.post("/ask")
def ask_endpoint(req: AskRequest):
    # `def` (et non `async def`) : l'appel LLM est bloquant, FastAPI l'exécute dans un thread.
    return ask(req.dataset_id, req.question, [h.model_dump() for h in req.history])
