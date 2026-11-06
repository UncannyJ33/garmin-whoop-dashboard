"""Garmin Personal API client (official API, bearer-token auth via httpx).

Failure policy: 204/empty/400/404 return "no data"; 401 retries once with a forced
token refresh; 403 means a key/scope problem; 429 and 5xx/network errors raise so the
caller can abort the run instead of advancing past a gap.
"""

import logging
import time
from datetime import date, datetime
from typing import Any

import httpx

from src.clients.garmin_personal_auth import (
    KEY_PAGE_URL,
    GarminKeyError,
    GarminPersonalAuth,
    GarminRateLimitError,
    GarminTransientError,
    get_default_auth,
)

logger = logging.getLogger(__name__)

_PAGE_LIMIT = 100
_MAX_PAGES = 100
_SLEEP_CORE_KEYS = ("sleepTimeSeconds", "sleepStartTimestampGMT", "sleepEndTimestampGMT")
_ACTIVITIES_PATH = "/activitylist-service/activities/search/activities"


# Metric fields read by transform_daily_summary in src/ingestion/garmin_pipeline.py.
# A daily summary where all of these are null carries no data (past history depth).
_DAILY_METRIC_FIELDS = (
    "totalSteps",
    "totalDistanceMeters",
    "activeKilocalories",
    "totalKilocalories",
    "restingHeartRate",
    "minHeartRate",
    "maxHeartRate",
    "averageStressLevel",
    "maxStressLevel",
    "bodyBatteryHighestValue",
    "bodyBatteryLowestValue",
    "averageSpo2",
    "lowestSpo2",
)


def _is_null(v: Any) -> bool:
    """True for None or an empty container."""
    return v is None or (isinstance(v, (dict, list, tuple, str)) and len(v) == 0)


def _all_null(d: dict) -> bool:
    """True when every top-level value is null (the API's "no data" shape)."""
    return all(_is_null(v) for v in d.values())


def _fmt_date(d: date | datetime | str) -> str:
    """Format a date/datetime/string to a YYYY-MM-DD string.

    Args:
        d: A date, datetime, or already-formatted string.

    Returns:
        ISO 8601 date string (YYYY-MM-DD).
    """
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


class GarminClient:
    """Synchronous client for the Garmin Personal API.

    Usage::

        client = GarminClient()
        activities = client.get_activities("2026-10-01", "2026-10-31")
    """

    def __init__(
        self,
        auth: GarminPersonalAuth | None = None,
        request_delay: float = 1.0,
        http: httpx.Client | None = None,
    ) -> None:
        """Initialise the client.

        Args:
            auth: Auth instance; defaults to the process-wide one.
            request_delay: Minimum seconds between consecutive API calls (per instance).
            http: HTTP client; defaults to the auth instance's shared client.
        """
        self._auth = auth or get_default_auth()
        self._http = http or self._auth.http
        self._request_delay = request_delay
        self._last_call_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_activities(
        self,
        start_date: date | datetime | str,
        end_date: date | datetime | str,
    ) -> list[dict]:
        """Fetch all activities in the date range (local start date), paging 100 at a time.

        Raises:
            GarminKeyError, GarminRateLimitError, GarminTransientError: on API failure.
        """
        s, e = _fmt_date(start_date), _fmt_date(end_date)
        out: list[dict] = []
        start = 0
        prev_first: Any = None
        for _ in range(_MAX_PAGES):
            page = self._get(
                _ACTIVITIES_PATH,
                {"startDate": s, "endDate": e, "start": start, "limit": _PAGE_LIMIT},
            )
            if not isinstance(page, list):
                raise GarminTransientError(
                    f"unexpected activities response (expected a list, got {type(page).__name__})"
                )
            if len(page) > _PAGE_LIMIT:
                raise GarminTransientError("activities page larger than requested limit")
            first = page[0].get("activityId") if page and isinstance(page[0], dict) else None
            if first is not None and first == prev_first:
                raise GarminTransientError("activities pagination did not advance")
            prev_first = first
            out.extend(page)
            if len(page) < _PAGE_LIMIT:
                return out
            start += _PAGE_LIMIT
        raise GarminTransientError(f"activities exceeded {_MAX_PAGES} pages")

    def get_daily_summary(self, date_: date | datetime | str) -> dict:
        """Fetch the daily user summary. Returns {} when there is no data."""
        data = self._get(
            "/usersummary-service/usersummary/daily", {"calendarDate": _fmt_date(date_)}
        )
        if not isinstance(data, dict) or _all_null(data):
            return {}
        if all(_is_null(data.get(k)) for k in _DAILY_METRIC_FIELDS):
            return {}
        return data

    def get_sleep(self, date_: date | datetime | str) -> dict | None:
        """Fetch the flat DailySleepDTO; None on 204/empty/{}/all-null (no watch worn)."""
        data = self._get("/sleep-service/sleep/dailySleep", {"date": _fmt_date(date_)})
        if not isinstance(data, dict) or _all_null(data):
            return None
        # The real no-watch response keeps booleans and sleepNeed blocks, so also
        # treat "no sleep duration and no start/end timestamps" as no data.
        if all(_is_null(data.get(k)) for k in _SLEEP_CORE_KEYS):
            return None
        return data

    def get_hrv(self, date_: date | datetime | str) -> dict | None:
        """Fetch HRV for a night; None on 204/empty/all-null/no ``hrvSummary``."""
        data = self._get(f"/hrv-service/hrv/{_fmt_date(date_)}")
        if not isinstance(data, dict) or _all_null(data):
            return None
        summary = data.get("hrvSummary")
        if not isinstance(summary, dict) or _all_null(summary):
            return None
        return data

    def get_user_settings(self) -> dict:
        """Fetch user settings; used as the key-validity probe. Never log the body."""
        data = self._get("/userprofile-service/userprofile/settings")
        if not isinstance(data, dict) or not data:
            raise GarminTransientError("unexpected user settings response")
        return data

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        """Sleep if needed to enforce the minimum delay between API calls."""
        elapsed = time.monotonic() - self._last_call_time
        wait = self._request_delay - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call_time = time.monotonic()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET a Personal API path and return parsed JSON, or None for no data."""
        url = f"{self._auth.base_url}{path}"
        force_refresh = False
        while True:
            self._rate_limit()
            headers = {
                "Authorization": f"Bearer {self._auth.get_token(force_refresh=force_refresh)}",
                "Accept": "application/json",
            }
            try:
                resp = self._http.get(url, params=params, headers=headers)
            except httpx.RequestError as exc:
                raise GarminTransientError(f"Garmin request failed: {type(exc).__name__}") from None
            status = resp.status_code
            if status == 401:
                if not force_refresh:
                    force_refresh = True
                    continue
                raise GarminKeyError(
                    f"Garmin rejected the bearer token twice; check your key at {KEY_PAGE_URL}"
                )
            if status == 403:
                raise GarminKeyError(
                    f"Garmin denied access (HTTP 403); check key scopes at {KEY_PAGE_URL}"
                )
            if status == 429:
                raise GarminRateLimitError("Garmin rate limited (HTTP 429)")
            if status >= 500:
                raise GarminTransientError(f"Garmin server error (HTTP {status})")
            if status in (400, 404):
                logger.warning("Garmin %s returned HTTP %s", path, status)
                return None
            if not 200 <= status < 300:
                raise GarminTransientError(f"Unexpected Garmin response for {path} (HTTP {status})")
            if status == 204 or not resp.content.strip():
                return None
            try:
                return resp.json()
            except ValueError:
                raise GarminTransientError(f"Garmin {path} returned invalid JSON") from None
