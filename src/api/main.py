from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.routes.auth import router as auth_router
from src.ingestion.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Garmin sync scheduler on startup, stop it on shutdown."""
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Fitness Dashboard API", version="0.1.0", lifespan=lifespan)

app.include_router(auth_router)


@app.get("/health")
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}
