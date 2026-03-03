from fastapi import FastAPI

from src.api.routes.auth import router as auth_router

app = FastAPI(title="Fitness Dashboard API", version="0.1.0")

app.include_router(auth_router)


@app.get("/health")
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}
