import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import settings
from src.api.routes.account import router as account_router
from src.api.routes.auth import router as auth_router
from src.api.routes.garmin_csv import router as garmin_csv_router
from src.api.routes.garmin_upload import router as garmin_upload_router
from src.api.routes.insights import router as insights_router
from src.api.routes.readiness import router as readiness_router
from src.api.routes.recovery import router as recovery_router
from src.api.routes.sleep import router as sleep_router
from src.api.routes.sync import router as sync_router
from src.api.routes.training import router as training_router
from src.api.routes.trends import router as trends_router
from src.api.routes.waitlist import router as waitlist_router
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
    logger.info("Whoop redirect URI: %s", settings.whoop_redirect_uri)
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

# ---------------------------------------------------------------------------
# Cache-Control middleware — lets browser skip round-trips on back-navigation
# ---------------------------------------------------------------------------

# Paths that should never be cached (mutable state or real-time data)
_NO_CACHE_PREFIXES = ("/api/sync/", "/api/auth/", "/api/webhooks/", "/api/waitlist")


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        path = request.url.path
        if not path.startswith("/api/"):
            return response
        # Skip non-GET and non-success responses
        if request.method != "GET" or response.status_code >= 400:
            return response
        # Mutable endpoints: no cache
        if any(path.startswith(p) for p in _NO_CACHE_PREFIXES):
            response.headers["Cache-Control"] = "no-store"
        else:
            # Analytics endpoints: private cache, browser may reuse for 5 min
            response.headers["Cache-Control"] = "private, max-age=300"
        return response


app.add_middleware(CacheControlMiddleware)

_cors_origins = settings.cors_origins if settings.cors_origins != ["*"] else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(account_router)
app.include_router(auth_router)
app.include_router(readiness_router)
app.include_router(workouts_router)
app.include_router(recovery_router)
app.include_router(sleep_router)
app.include_router(trends_router)
app.include_router(training_router)
app.include_router(insights_router)
app.include_router(sync_router)
app.include_router(garmin_csv_router)
app.include_router(garmin_upload_router)
app.include_router(webhooks_router)
app.include_router(waitlist_router)


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}


# Serve React frontend static files (production build)
_DIST = Path(__file__).parent.parent.parent / "frontend-react" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """Serve index.html for all non-API routes (React SPA).

        Also handles sub-apps (e.g. /demo) whose index.html lives in a
        subdirectory of dist — serves dist/<path>/index.html when present.
        """
        file = _DIST / full_path
        if file.is_file():
            return FileResponse(file)
        if (file / "index.html").is_file():
            return FileResponse(file / "index.html")
        return FileResponse(_DIST / "index.html")
