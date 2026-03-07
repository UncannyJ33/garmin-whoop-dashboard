import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from src.api.routes.auth import router as auth_router
from src.api.routes.readiness import router as readiness_router
from src.api.routes.sleep import router as sleep_router
from src.api.routes.sync import router as sync_router
from src.api.routes.trends import router as trends_router
from src.api.routes.webhooks import router as webhooks_router
from src.api.routes.workouts import router as workouts_router
from src.ingestion.scheduler import start_scheduler, stop_scheduler
from src.logging_config import configure_logging

configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Garmin sync scheduler on startup, stop it on shutdown."""
    logger.info("Fitness Dashboard API starting up (log_level=%s)", settings.log_level)
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Fitness Dashboard API shut down")


app = FastAPI(
    title="Fitness Dashboard API",
    version="0.2.0",
    description=(
        "REST API for Garmin + Whoop fitness data. "
        "Exposes readiness scores, enriched workouts, sleep insights, "
        "trend analytics, and sync management."
    ),
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(readiness_router)
app.include_router(workouts_router)
app.include_router(sleep_router)
app.include_router(trends_router)
app.include_router(sync_router)
app.include_router(webhooks_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}
