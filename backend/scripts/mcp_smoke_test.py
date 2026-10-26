"""Test de fumée : lance le serveur MCP en stdio et appelle les outils.

Usage (depuis backend/) :  python scripts/mcp_smoke_test.py
"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _text(result) -> str:
    return "".join(getattr(c, "text", "") for c in result.content)


async def main() -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server.server"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Outils exposés :", [t.name for t in tools.tools])

            res = await session.call_tool("list_datasets", {})
            datasets = json.loads(_text(res))["datasets"]
            print("Datasets :", len(datasets))
            if not datasets:
                print("Aucun dataset : uploadez-en un via l'API/Streamlit puis relancez.")
                return

            ds_id = datasets[0]["id"]
            schema = await session.call_tool("get_dataset_schema", {"dataset_id": ds_id})
            print("Schéma :", _text(schema)[:300])

            ok = await session.call_tool(
                "run_sql_query",
                {"dataset_id": ds_id, "sql": "SELECT COUNT(*) AS n FROM data"},
            )
            print("SELECT COUNT :", _text(ok))

            bad = await session.call_tool(
                "run_sql_query", {"dataset_id": ds_id, "sql": "DROP TABLE data"}
            )
            print("DROP (doit être refusé) -> isError =", bad.isError, "|", _text(bad)[:150])


if __name__ == "__main__":
    asyncio.run(main())
