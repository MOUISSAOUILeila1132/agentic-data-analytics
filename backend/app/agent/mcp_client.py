"""Client MCP de l'agent : l'exécution SQL passe par le serveur MCP.

Le serveur (`app.mcp_server.server`) est lancé UNE fois, en sous-processus (stdio), puis
réutilisé pour tous les appels. Une session asynchrone vit dans un thread dédié ; les nœuds
LangGraph (synchrones) l'appellent via `run_sql_query`, sans changer de signature.

Interrupteur : AGENT_USE_MCP=false dans .env => appel direct de sql_engine (comme avant).
"""
import asyncio
import atexit
import concurrent.futures
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from time import perf_counter

from fastapi import HTTPException
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from app.core.config import settings
from app.services.context_service import build_schema_context
from app.services.dashboard_payload import compute_dashboard
from app.services.sql_engine import run_readonly_query

log = logging.getLogger("mcp_client")
# Logger de uvicorn : ses lignes « INFO: » s'affichent dans la console du backend
# (les logs du sous-processus MCP, eux, ne sont pas toujours visibles sous Windows).
_console = logging.getLogger("uvicorn.error")

BACKEND_DIR = Path(__file__).resolve().parents[2]  # dossier backend/
_STATUS_RE = re.compile(r"\[(\d{3})\]\s*(.*)", re.DOTALL)


class _McpBridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._session: ClientSession | None = None
        self._ready = threading.Event()

    # ---- thread dédié : boucle asyncio + session MCP
    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(BACKEND_DIR),
            # même dossier de données que l'API, quel que soit le répertoire courant
            env={**get_default_environment(), "DATA_DIR": str(settings.data_dir.resolve())},
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as exc:  # noqa: BLE001 : on journalise, l'appelant fera une erreur propre
            log.error("Session MCP terminée : %r", exc)
        finally:
            self._session = None
            self._ready.set()  # débloque un éventuel appelant en attente

    def _thread_main(self) -> None:
        # Sous Windows, il faut une boucle Proactor pour lancer un sous-processus
        # (uvicorn peut avoir installé une politique « Selector » qui ne le permet pas).
        if sys.platform == "win32":
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._main())
        finally:
            loop.close()

    # ---- cycle de vie
    def _shutdown_locked(self) -> None:
        if self._thread and self._thread.is_alive() and self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=10)
        self._thread = self._loop = self._stop = self._session = None

    def _ensure(self) -> None:
        with self._lock:
            if self._session is not None and self._thread and self._thread.is_alive():
                return
            self._shutdown_locked()
            self._ready.clear()
            self._thread = threading.Thread(target=self._thread_main, daemon=True, name="mcp-client")
            self._thread.start()
            if not self._ready.wait(timeout=settings.mcp_start_timeout_s) or self._session is None:
                self._shutdown_locked()
                raise HTTPException(503, "Serveur MCP indisponible (démarrage impossible).")

    def close(self) -> None:
        with self._lock:
            self._shutdown_locked()

    # ---- appel d'outil (thread-safe)
    def call(self, name: str, arguments: dict):
        for _ in range(2):  # 1 reconnexion automatique si le serveur est tombé
            self._ensure()
            session, loop = self._session, self._loop
            if session is None or loop is None:
                continue
            future = asyncio.run_coroutine_threadsafe(session.call_tool(name, arguments), loop)
            try:
                return future.result(timeout=settings.mcp_call_timeout_s)
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise HTTPException(504, "Le serveur MCP a mis trop de temps à répondre.")
            except Exception as exc:  # noqa: BLE001
                log.warning("Appel MCP échoué (%r) : reconnexion…", exc)
                with self._lock:
                    self._shutdown_locked()
        raise HTTPException(503, "Connexion au serveur MCP perdue.")


_bridge = _McpBridge()
atexit.register(_bridge.close)


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


def _call_tool(name: str, arguments: dict) -> dict:
    """Appelle un outil MCP et renvoie son résultat JSON ; les erreurs deviennent des HTTPException."""
    start = perf_counter()
    result = _bridge.call(name, arguments)
    _console.info(
        "MCP · outil %s · %.0f ms%s", name, (perf_counter() - start) * 1000, " · erreur" if result.isError else ""
    )
    text = _text(result)
    if result.isError:
        match = _STATUS_RE.search(text)
        # sans code reconnu (bug inattendu) : 502, donc l'agent ne le « corrige » pas en boucle
        status, detail = (int(match.group(1)), match.group(2).strip()) if match else (502, text)
        raise HTTPException(status, detail)
    try:
        return json.loads(text)
    except ValueError:
        raise HTTPException(502, "Réponse du serveur MCP illisible.")


def run_sql_query(dataset_id: str, sql: str, max_rows: int | None = None) -> dict:
    """Même contrat que `sql_engine.run_readonly_query` (mêmes erreurs HTTPException)."""
    if not settings.agent_use_mcp:
        return run_readonly_query(dataset_id, sql, max_rows)
    arguments: dict = {"dataset_id": dataset_id, "sql": sql}
    if max_rows:
        arguments["max_rows"] = max_rows
    return _call_tool("run_sql_query", arguments)


def get_data_context(dataset_id: str) -> str:
    """Même contrat que `build_schema_context` : description de la table `data` pour le LLM."""
    if not settings.agent_use_mcp:
        return build_schema_context(dataset_id)
    return _call_tool("get_data_context", {"dataset_id": dataset_id})["context"]


def get_dashboard(
    dataset_id: str,
    categorical: dict[str, list[str]] | None = None,
    dates: dict[str, list[str]] | None = None,
    include_figures: bool = True,
) -> dict:
    """Même contrat que `dashboard_payload.compute_dashboard` (mêmes erreurs HTTPException)."""
    if not settings.dashboard_use_mcp:
        return compute_dashboard(dataset_id, categorical, dates, include_figures)
    return _call_tool(
        "get_dashboard",
        {
            "dataset_id": dataset_id,
            "categorical": categorical or {},
            "dates": dates or {},
            "include_figures": include_figures,
        },
    )


def mcp_status() -> dict:
    """Diagnostic : MCP est-il activé, le serveur répond-il, et dans quel processus tourne-t-il ?"""
    status = {
        "api_pid": os.getpid(),
        "agent_use_mcp": settings.agent_use_mcp,
        "dashboard_use_mcp": settings.dashboard_use_mcp,
        "mcp": "désactivé (AGENT_USE_MCP et DASHBOARD_USE_MCP sont à false)",
    }
    if settings.agent_use_mcp or settings.dashboard_use_mcp:
        try:
            status["mcp"] = {"connected": True, **_call_tool("server_info", {})}
        except HTTPException as exc:
            status["mcp"] = {"connected": False, "error": exc.detail}
    return status
