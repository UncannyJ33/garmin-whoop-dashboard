"""Probe the live Garmin Personal API and save raw samples (gitignored).

Raw responses go to ``data/garmin_personal_samples/``. The API key and access
token are never printed or written. Usage::

    .venv/bin/python scripts/garmin_personal_probe.py [--no-watch-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
SAMPLES = Path(__file__).resolve().parent.parent / "data" / "garmin_personal_samples"
DELAY_S = 1.0


class RateLimited(Exception):
    """Raised on a 429 so the probe stops calling the API."""


class Probe:
    """Throttled GET client that records status, content type and body length."""

    def __init__(self, client: httpx.Client, token: str) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self.last = 0.0
        self.log: list[dict[str, Any]] = []

    def get(
        self, name: str, path: str, params: dict[str, Any] | None = None, save: bool = True
    ) -> Any:
        """GET ``path``; save the raw body as ``<name>.json``; return parsed JSON or None."""
        wait = DELAY_S - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        resp = self.client.get(BASE_URL + path, params=params, headers=self.headers)
        self.last = time.monotonic()
        ctype = resp.headers.get("Content-Type", "")
        self.log.append(
            {"name": name, "status": resp.status_code, "ctype": ctype, "len": len(resp.content)}
        )
        print(f"{name:32s} {resp.status_code} {ctype[:30]:30s} len={len(resp.content)}")
        if resp.status_code == 429:
            print("429 Retry-After:", resp.headers.get("Retry-After"))
            raise RateLimited
        data: Any = None
        if resp.status_code == 200 and "json" in ctype.lower() and resp.content:
            data = resp.json()
            if save:
                (SAMPLES / f"{name}.json").write_text(json.dumps(data, indent=2))
        return data


def jwt_exp(token: str) -> datetime:
    """Decode the JWT ``exp`` claim (unverified) as a UTC datetime."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return datetime.fromtimestamp(json.loads(base64.urlsafe_b64decode(payload))["exp"], tz=UTC)


def as_list(data: Any) -> list[dict[str, Any]]:
    """Return the activity list whether the API wraps it or not."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def main() -> int:
    """Run the probe."""
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--no-watch-date",
        default=None,
        help="a night without the watch (default: first empty found)",
    )
    args = ap.parse_args()
    load_dotenv()
    key = os.environ.get("GARMIN_PERSONAL_API_KEY")
    if not key:
        print("GARMIN_PERSONAL_API_KEY not set")
        return 2
    SAMPLES.mkdir(parents=True, exist_ok=True)
    today = date.today()
    yday = (today - timedelta(days=1)).isoformat()
    old = (today - timedelta(days=730)).isoformat()

    with httpx.Client(timeout=30) as client:
        try:
            resp = client.post(
                BASE_URL + TOKEN_PATH,
                headers={"Authorization": f"ApiKey {key}", "Accept": "*/*"},
            )
        except httpx.TransportError as exc:
            print(f"token exchange network failure: {type(exc).__name__}")
            return 4
        print("token exchange:", resp.status_code)
        if resp.status_code != 200:
            return 3
        token = resp.text.strip()
        print(
            "token exp:",
            jwt_exp(token).isoformat(),
            "| lifetime h:",
            round((jwt_exp(token) - datetime.now(UTC)).total_seconds() / 3600, 1),
        )
        p = Probe(client, token)
        try:
            run(p, today, yday, old, args.no_watch_date)
        except RateLimited:
            print("stopped on 429")
        except httpx.TransportError as exc:
            print(f"network failure, stopping: {type(exc).__name__}")
            (SAMPLES / "_probe_log.json").write_text(json.dumps(p.log, indent=2))
            return 4
        (SAMPLES / "_probe_log.json").write_text(json.dumps(p.log, indent=2))
    return 0


def run(p: Probe, today: date, yday: str, old: str, no_watch: str | None) -> None:
    """Execute all probe calls in order."""
    p.get("user_settings", "/userprofile-service/userprofile/settings")
    acts_raw = p.get(
        "activities_30d",
        "/activitylist-service/activities/search/activities",
        {
            "startDate": (today - timedelta(days=30)).isoformat(),
            "endDate": today.isoformat(),
            "start": 0,
            "limit": 100,
        },
    )
    acts = as_list(acts_raw)
    print("activities (30d):", len(acts), "| top-level type:", type(acts_raw).__name__)
    p.get("daily_summary", "/usersummary-service/usersummary/daily", {"calendarDate": yday})
    p.get("sleep_yesterday", "/sleep-service/sleep/dailySleep", {"date": yday})
    p.get("hrv_yesterday", f"/hrv-service/hrv/{yday}")

    # Scan last 14 nights for populated / empty sleep + HRV.
    empty_night = no_watch
    for i in range(2, 16):
        d = (today - timedelta(days=i)).isoformat()
        s = p.get(f"sleep_scan_{d}", "/sleep-service/sleep/dailySleep", {"date": d})
        h = p.get(f"hrv_scan_{d}", f"/hrv-service/hrv/{d}")
        print(
            f"  {d}: sleep_keys={len(s) if isinstance(s, dict) else None} hrv={'data' if h else 'none'}"
        )
        if not empty_night and not h:
            empty_night = d
    if empty_night:
        p.get("sleep_no_watch", "/sleep-service/sleep/dailySleep", {"date": empty_night})
        p.get("hrv_no_watch", f"/hrv-service/hrv/{empty_night}")
    print("no-watch night used:", empty_night)

    # Strength activity: search back up to 365 days in 100-record pages.
    def is_strength(a: dict[str, Any]) -> bool:
        return bool(a.get("summarizedExerciseSets"))

    found = [a for a in acts if is_strength(a)]
    if not found:
        for chunk in range(1, 13):
            end = today - timedelta(days=30 * chunk)
            start = end - timedelta(days=30)
            data = as_list(
                p.get(
                    f"activities_scan_{chunk}",
                    "/activitylist-service/activities/search/activities",
                    {
                        "startDate": start.isoformat(),
                        "endDate": end.isoformat(),
                        "start": 0,
                        "limit": 100,
                    },
                    save=False,
                )
            )
            found = [a for a in data if is_strength(a)]
            if found:
                (SAMPLES / "strength_activity.json").write_text(json.dumps(found[0], indent=2))
                break
    else:
        (SAMPLES / "strength_activity.json").write_text(json.dumps(found[0], indent=2))
    print("strength activity found:", bool(found))

    # History depth (730 days).
    p.get("daily_730d", "/usersummary-service/usersummary/daily", {"calendarDate": old})
    p.get("sleep_730d", "/sleep-service/sleep/dailySleep", {"date": old})
    old_start = (date.fromisoformat(old) - timedelta(days=15)).isoformat()
    old_end = (date.fromisoformat(old) + timedelta(days=15)).isoformat()
    olds = as_list(
        p.get(
            "activities_730d",
            "/activitylist-service/activities/search/activities",
            {"startDate": old_start, "endDate": old_end, "start": 0, "limit": 100},
        )
    )
    print("activities near 730d:", len(olds))
    if olds and olds[0].get("activityId") is not None:
        aid = olds[0]["activityId"]
        wait = DELAY_S - (time.monotonic() - p.last)
        time.sleep(max(wait, 0))
        r = p.client.get(
            f"{BASE_URL}/download-service/files/activity/{aid}",
            headers={"Authorization": p.headers["Authorization"]},
        )
        print("FIT download 730d:", r.status_code, r.headers.get("Content-Type"), len(r.content))
        if r.status_code == 429:
            print("429 Retry-After:", r.headers.get("Retry-After"))
            raise RateLimited


if __name__ == "__main__":
    sys.exit(main())
