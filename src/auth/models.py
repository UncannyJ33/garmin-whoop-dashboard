"""SQLAlchemy User model for JWT-based authentication."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, Integer, String

from src.database.models import Base


class User(Base):
    """Application user account."""

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(String, nullable=False, default=lambda: datetime.now(UTC).isoformat())
    is_active = Column(Boolean, default=True, nullable=False)
    sleep_target_minutes = Column(Integer, nullable=False, default=480, server_default="480")
