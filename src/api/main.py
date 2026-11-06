import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from config.settings import settings
from src.api.routes.account import router as account_router
from src.api.routes.auth import router as auth_router
from src.api.routes.garmin_upload import router as garmin_upload_router
from src.api.routes.insights import router as insights_router
from src.api.routes.readiness import router as readiness_router
from src.api.routes.recovery import router as recovery_router
from src.api.routes.sleep import router as sleep_router
from src.api.routes.sync import router as sync_router
from src.api.routes.training import router as training_router
from src.api.routes.trends import router as trends_router
from src.api.routes.workouts import router as workouts_router
from src.ingestion.scheduler import start_scheduler, stop_scheduler
from src.logging_config import configure_logging

configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the Garmin sync scheduler on startup, stop it on shutdown."""
    if not settings.jwt_secret:
        raise RuntimeError(
            "JWT_SECRET is not set. Refusing to start: an empty secret lets anyone forge "
            "tokens. Set JWT_SECRET to a long random string."
        )
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
_NO_CACHE_PREFIXES = ("/api/sync/", "/api/auth/")


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
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


def install_cors(app: FastAPI, origins: list[str]) -> None:
    """Add CORSMiddleware to ``app`` only when ``origins`` is non-empty (same-origin by default)."""
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


install_cors(app, settings.cors_origins)

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
app.include_router(garmin_upload_router)


@app.get("/health", tags=["health"])
@app.get("/api/health", tags=["health"])
async def health() -> dict:
    """Basic health check."""
    return {"status": "ok"}


# Serve React frontend static files (production build)
_DIST = Path(__file__).parent.parent.parent / "frontend-react" / "dist"


def _spa_file(dist: Path, full_path: str) -> Path | None:
    """Decide what the SPA catch-all serves for ``full_path``.

    Returns None for ``api`` paths (caller must 404). Returns the requested
    file only if, once resolved (symlinks and ``..`` included), it is a file
    inside ``dist``; otherwise ``dist/index.html``.
    """
    if full_path == "api" or full_path.startswith("api/"):
        return None
    root = dist.resolve()
    try:
        resolved = (root / full_path).resolve()
    except ValueError:  # e.g. NUL byte in path
        return dist / "index.html"
    if resolved.is_file() and resolved.is_relative_to(root):
        return resolved
    return dist / "index.html"


if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        """Serve index.html for all non-API routes (React SPA); 404 for unknown /api/*."""
        file = _spa_file(_DIST, full_path)
        if file is None:
            raise HTTPException(status_code=404, detail="Not found")
        if file.name in ("index.html", "sw.js"):
            return FileResponse(file, headers={"Cache-Control": "no-cache"})
        return FileResponse(file)
