from fastapi import FastAPI

from app.api import agent, dashboard, datasets, health, query

app = FastAPI(title="Agentic AI Data Analytics", version="0.1.0")
app.include_router(datasets.router)
app.include_router(dashboard.router)
app.include_router(query.router)
app.include_router(agent.router)
app.include_router(health.router)


@app.get("/health")
def health():
    return {"status": "ok"}