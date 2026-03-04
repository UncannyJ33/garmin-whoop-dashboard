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

    # Garmin credentials
    garmin_email: str
    garmin_password: str
    garmin_token_dir: str

    # Database
    database_url: str

    # Server
    app_port: int
    streamlit_port: int

    # Logging
    log_level: str


settings = Settings(
    whoop_client_id=os.getenv("WHOOP_CLIENT_ID", ""),
    whoop_client_secret=os.getenv("WHOOP_CLIENT_SECRET", ""),
    whoop_redirect_uri=os.getenv(
        "WHOOP_REDIRECT_URI", "http://localhost:8000/api/auth/whoop/callback"
    ),
    garmin_email=os.getenv("GARMIN_EMAIL", ""),
    garmin_password=os.getenv("GARMIN_PASSWORD", ""),
    garmin_token_dir=os.getenv("GARMIN_TOKEN_DIR", "data/garmin_tokens"),
    database_url=os.getenv("DATABASE_URL", "sqlite:///data/fitness_dashboard.db"),
    app_port=int(os.getenv("APP_PORT", "8000")),
    streamlit_port=int(os.getenv("STREAMLIT_PORT", "8501")),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
)
