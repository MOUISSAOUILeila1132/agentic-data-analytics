from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.agent.mcp_client import get_dashboard

router = APIRouter(prefix="/datasets", tags=["dashboard"])


class DashboardRequest(BaseModel):
    categorical: dict[str, list[str]] = Field(default_factory=dict)  # colonne -> valeurs retenues
    dates: dict[str, list[str]] = Field(default_factory=dict)  # colonne -> [début, fin] (ISO)


@router.post("/{dataset_id}/dashboard")
def dashboard(dataset_id: str, req: DashboardRequest):
    # Le dashboard est construit par l'outil MCP `get_dashboard` (mode complet, avec figures Plotly).
    return get_dashboard(dataset_id, req.categorical, req.dates, include_figures=True)
