import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    # Whoop OAuth
    whoop_client_id: str
    whoop_client_secret: str
    whoop_redirect_uri: str

    # Database
    database_url: str

    # Server
    app_port: int
    streamlit_port: int
    cors_origins: list

    # Garmin Personal API (official, key -> 24h bearer JWT)
    garmin_personal_api_key: str
    garmin_personal_api_base_url: str

    # Scheduler
    garmin_poll_interval_minutes: int

    # JWT auth
    jwt_secret: str
    jwt_algorithm: str

    # Logging
    log_level: str

    # Feature flags
    whoop_public_oauth_enabled: bool
    # Per-user Whoop OAuth allowlist — comma-separated user IDs that can connect
    # Whoop even when whoop_public_oauth_enabled is False
    whoop_allowed_user_ids: list[str]


settings = Settings(
    whoop_client_id=os.getenv("WHOOP_CLIENT_ID", ""),
    whoop_client_secret=os.getenv("WHOOP_CLIENT_SECRET", ""),
    whoop_redirect_uri=os.getenv(
        "WHOOP_REDIRECT_URI", "http://localhost:8000/api/auth/whoop/callback"
    ),
    database_url=os.getenv("DATABASE_URL", "sqlite:///data/fitness_dashboard.db"),
    app_port=int(os.getenv("PORT") or os.getenv("APP_PORT", "8000")),
    streamlit_port=int(os.getenv("STREAMLIT_PORT", "8501")),
    cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()],
    garmin_personal_api_key=os.getenv("GARMIN_PERSONAL_API_KEY", ""),
    garmin_personal_api_base_url=os.getenv("GARMIN_PERSONAL_API_BASE_URL")
    or "https://personal.connectapi.garmin.com",
    garmin_poll_interval_minutes=int(os.getenv("GARMIN_POLL_INTERVAL_MINUTES", "30")),
    jwt_secret=os.getenv("JWT_SECRET", ""),
    jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    whoop_public_oauth_enabled=os.getenv("WHOOP_PUBLIC_OAUTH_ENABLED", "false").lower() == "true",
    whoop_allowed_user_ids=[
        uid.strip() for uid in os.getenv("WHOOP_ALLOWED_USER_IDS", "").split(",") if uid.strip()
    ],
)
