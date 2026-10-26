from fastapi import APIRouter

from app.agent.mcp_client import mcp_status

router = APIRouter(tags=["health"])


@router.get("/health/mcp")
def health_mcp():
    """Prouve que MCP est utilisé : `mcp.pid` doit être différent de `api_pid` (processus séparé)."""
    return mcp_status()
