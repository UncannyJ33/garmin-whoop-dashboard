"""Garmin API client wrapping the garminconnect library.

Each public method is independently resilient: a broken endpoint returns None
and logs a warning rather than crashing the caller.
"""

import logging
import time
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from garth.exc import GarthHTTPError

from src.clients.garmin_auth import GarminAuth, _status_code

logger = logging.getLogger(__name__)

# Seconds to sleep after a 429 before retrying
_RATE_LIMIT_SLEEP_S = 60.0


def _fmt_date(d: date | datetime | str) -> str:
    """Format a date/datetime/string to the YYYY-MM-DD string garminconnect expects.

    Args:
        d: A date, datetime, or already-formatted string.

    Returns:
        ISO 8601 date string (YYYY-MM-DD).
    """
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


class GarminClient:
    """Synchronous client for the Garmin Connect API via garminconnect.

    Wraps every garminconnect call with:
    - Rate limiting (configurable delay between requests)
    - Automatic re-auth and single retry on 401
    - 60-second sleep and single retry on 429
    - Graceful None return on 400/404 and unexpected errors

    Usage::

        client = GarminClient()
        activities = client.get_activities("2024-01-01", "2024-01-31")
    """

    def __init__(
        self,
        auth: GarminAuth | None = None,
        request_delay: float = 1.5,
    ) -> None:
        """Initialise the client.

        Args:
            auth: Pre-built GarminAuth instance. Defaults to a new one.
            request_delay: Minimum seconds between consecutive API calls.
        """
        self._auth = auth or GarminAuth()
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
        """Fetch all activities in the given date range.

        Args:
            start_date: Range start (inclusive).
            end_date: Range end (inclusive).

        Returns:
            List of activity dicts, or an empty list on error.
        """
        start, end = _fmt_date(start_date), _fmt_date(end_date)
        result = self._call(lambda c: c.get_activities_by_date(start, end))
        return result if result is not None else []

    def get_activity_detail(self, activity_id: str | int) -> dict | None:
        """Fetch full detail for a single activity (used for running dynamics).

        Args:
            activity_id: Garmin activity ID.

        Returns:
            Activity detail dict, or None on error.
        """
        aid = str(activity_id)
        return self._call(lambda c: c.get_activity(aid))

    def get_exercise_sets(self, activity_id: str | int) -> dict | None:
        """Fetch exercise set data for a single strength training activity.

        Args:
            activity_id: Garmin activity ID.

        Returns:
            Dict with an ``exerciseSets`` list, or None on error / unavailable.
        """
        aid = str(activity_id)
        return self._call(lambda c: c.get_activity_exercise_sets(aid))

    def get_daily_summary(self, date_: date | datetime | str) -> dict:
        """Combine stats, heart rate, body battery, and stress into one dict.

        Each sub-call is independent — a failed endpoint contributes an empty
        dict rather than preventing the others from running.

        Args:
            date_: The calendar date to fetch.

        Returns:
            Merged dict with keys from all four endpoints (non-overlapping keys
            are preserved; overlapping keys prefer the later merge source).
        """
        d = _fmt_date(date_)

        stats = self._call(lambda c: c.get_stats(d)) or {}
        heart_rates = self._call(lambda c: c.get_heart_rates(d)) or {}
        body_battery_list = self._call(lambda c: c.get_body_battery(d, d)) or []
        stress = self._call(lambda c: c.get_stress_data(d)) or {}

        # get_body_battery returns a list; grab the first entry for this date
        body_battery = body_battery_list[0] if body_battery_list else {}

        return {**stats, **heart_rates, **body_battery, **stress}

    def get_sleep(self, date_: date | datetime | str) -> dict | None:
        """Fetch sleep data for a single date.

        Args:
            date_: The calendar date to fetch.

        Returns:
            Sleep data dict, or None on error.
        """
        d = _fmt_date(date_)
        return self._call(lambda c: c.get_sleep_data(d))

    def get_hrv(self, date_: date | datetime | str) -> dict | None:
        """Fetch HRV data for a single date.

        Args:
            date_: The calendar date to fetch.

        Returns:
            HRV data dict, or None if unavailable or on error.
        """
        d = _fmt_date(date_)
        return self._call(lambda c: c.get_hrv_data(d))

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

    def _call(
        self,
        make_call: Callable[[Any], Any],
        *,
        _retried: bool = False,
    ) -> Any:
        """Execute a garminconnect API call with rate limiting and error handling.

        Args:
            make_call: Callable that receives a Garmin client and returns a result.
            _retried: Internal flag — prevents infinite retry loops.

        Returns:
            The API result, or None if the call failed unrecoverably.
        """
        self._rate_limit()

        try:
            client = self._auth.get_client()
            return make_call(client)

        except GarthHTTPError as exc:
            code = _status_code(exc)

            if code in (400, 404):
                logger.warning("Garmin API: endpoint unavailable (HTTP %s) — skipping", code)
                return None

            if code == 401 and not _retried:
                logger.warning("Garmin API: session expired (401) — re-authenticating and retrying")
                self._auth._client = None  # force GarminAuth to rebuild the session
                return self._call(make_call, _retried=True)

            if code == 429 and not _retried:
                logger.error(
                    "Garmin API: rate limited (429) — sleeping %ds then retrying",
                    int(_RATE_LIMIT_SLEEP_S),
                )
                time.sleep(_RATE_LIMIT_SLEEP_S)
                return self._call(make_call, _retried=True)

            logger.error("Garmin API: unhandled HTTP %s: %s", code, exc)
            return None

        except Exception as exc:  # noqa: BLE001
            # Re-raise rate limit errors so the pipeline aborts on first failure
            # rather than making N more failed OAuth calls (one per API call).
            err_msg = str(exc)
            if "429" in err_msg or "rate limit" in err_msg.lower() or "too many" in err_msg.lower():
                raise
            logger.error("Garmin API: unexpected error: %s", exc)
            return None
