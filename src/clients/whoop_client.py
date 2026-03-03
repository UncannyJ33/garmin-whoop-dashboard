import asyncio
import logging
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from src.clients.whoop_auth import WhoopAuth

logger = logging.getLogger(__name__)

WHOOP_BASE_URL = "https://api.prod.whoop.com/developer/v2"

_MAX_RATE_LIMIT_RETRIES = 5
_MAX_SERVER_RETRIES = 3
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 60.0


class WhoopAPIError(Exception):
    """Raised when a Whoop API request fails after all retries."""


class WhoopClient:
    """Async HTTP client for the Whoop REST API v2.

    Handles authentication, pagination, and retry logic for all API calls.
    Intended to be instantiated per-request with an active database session.
    """

    def __init__(self, db: Session, auth: WhoopAuth | None = None) -> None:
        """Initialise the client with a database session and optional auth handler.

        Args:
            db: Active SQLAlchemy session used for token reads and writes.
            auth: Pre-built WhoopAuth instance, useful for injection in tests.
                  Defaults to a new WhoopAuth instance.
        """
        self._db = db
        self._auth = auth or WhoopAuth()

    async def _get_headers(self) -> dict[str, str]:
        """Return Authorization headers with a valid (auto-refreshed) token."""
        token = await self._auth.get_valid_token(self._db)
        return {"Authorization": f"Bearer {token}"}

    async def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        _token_refreshed: bool = False,
    ) -> dict:
        """Execute a GET request with retry logic for 429, 401, and 5xx.

        Args:
            path: API path relative to WHOOP_BASE_URL.
            params: Optional query parameters.
            _token_refreshed: Internal flag — prevents infinite 401 loops.

        Returns:
            Parsed JSON response as a dict.

        Raises:
            WhoopAPIError: After exhausting retries or on an unrecoverable error.
        """
        url = f"{WHOOP_BASE_URL}{path}"

        for attempt in range(_MAX_RATE_LIMIT_RETRIES + 1):
            headers = await self._get_headers()

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, params=params or {})

            if response.status_code == 200:
                return response.json()

            # 401 — refresh token once and retry
            if response.status_code == 401:
                if _token_refreshed:
                    logger.error("401 on %s even after token refresh", path)
                    raise WhoopAPIError(f"401 on {path} after token refresh — re-authorize")
                logger.warning("401 on %s — refreshing token and retrying", path)
                await self._auth.refresh_access_token(self._db)
                return await self._request(path, params, _token_refreshed=True)

            # 429 — exponential backoff up to _MAX_RATE_LIMIT_RETRIES
            if response.status_code == 429:
                if attempt >= _MAX_RATE_LIMIT_RETRIES:
                    raise WhoopAPIError(
                        f"Rate limited on {path} after {_MAX_RATE_LIMIT_RETRIES} retries"
                    )
                delay = min(_BACKOFF_BASE_S * (2**attempt), _BACKOFF_MAX_S)
                logger.warning(
                    "429 on %s — backing off %.0fs (attempt %d/%d)",
                    path, delay, attempt + 1, _MAX_RATE_LIMIT_RETRIES,
                )
                await asyncio.sleep(delay)
                continue

            # 5xx — backoff up to _MAX_SERVER_RETRIES
            if response.status_code >= 500:
                if attempt >= _MAX_SERVER_RETRIES:
                    logger.error(
                        "%d on %s after %d retries: %s",
                        response.status_code, path, _MAX_SERVER_RETRIES, response.text[:300],
                    )
                    raise WhoopAPIError(
                        f"{response.status_code} on {path} after {_MAX_SERVER_RETRIES} retries"
                    )
                delay = min(_BACKOFF_BASE_S * (2**attempt), _BACKOFF_MAX_S)
                logger.error(
                    "%d on %s — backing off %.0fs (attempt %d/%d)",
                    response.status_code, path, delay, attempt + 1, _MAX_SERVER_RETRIES,
                )
                await asyncio.sleep(delay)
                continue

            # All other errors — fail immediately
            logger.error(
                "GET %s → %d: %s", path, response.status_code, response.text[:300]
            )
            raise WhoopAPIError(
                f"GET {path} returned {response.status_code}: {response.text[:300]}"
            )

        raise WhoopAPIError(f"GET {path} exhausted all retries")

    async def _get_paginated(
        self,
        path: str,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict]:
        """Fetch all pages from a collection endpoint and combine into one list.

        Args:
            path: API path for the collection endpoint.
            start_date: Range start — date, datetime, or ISO 8601 string.
            end_date: Range end.

        Returns:
            All records from all pages combined into a single list.
        """
        start = start_date.isoformat() if hasattr(start_date, "isoformat") else start_date
        end = end_date.isoformat() if hasattr(end_date, "isoformat") else end_date

        params: dict[str, Any] = {"start": start, "end": end}
        records: list[dict] = []

        while True:
            data = await self._request(path, params)
            records.extend(data.get("records", []))
            next_token = data.get("next_token")
            if not next_token:
                break
            params = {"start": start, "end": end, "nextToken": next_token}

        return records

    async def get_cycles(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict]:
        """Fetch all physiological cycles in the given date range."""
        return await self._get_paginated("/cycle", start_date, end_date)

    async def get_recovery(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict]:
        """Fetch all recovery records in the given date range."""
        return await self._get_paginated("/recovery", start_date, end_date)

    async def get_sleep(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict]:
        """Fetch all sleep records in the given date range."""
        return await self._get_paginated("/activity/sleep", start_date, end_date)

    async def get_workouts(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict]:
        """Fetch all workout records in the given date range."""
        return await self._get_paginated("/activity/workout", start_date, end_date)

    async def get_body_measurements(self) -> dict:
        """Fetch user body measurements (height, weight, max HR)."""
        return await self._request("/user/measurement/body")

    async def get_profile(self) -> dict:
        """Fetch basic user profile (name, email, user ID)."""
        return await self._request("/user/profile/basic")
