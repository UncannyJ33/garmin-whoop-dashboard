"""In-process API smoke check against the database in ``DATABASE_URL``.

Runs every safe GET route of the FastAPI app through ``TestClient`` (no network
listener, no running server, scheduler patched out) as the single owner user,
using an access token minted in-process. Routes that would reach Garmin or
Whoop are skipped. Routes are discovered from the OpenAPI schema, so new GET
routes are covered automatically.

Per response it checks: status (200, or 204 when documented), valid JSON, no
bare ``NaN``/``Infinity`` tokens, no Python-repr leaks inside JSON strings, and
latency (> 2 s is flagged slow). Response bodies are never printed or saved.

Usage:
    source <env that exports DATABASE_URL> && python scripts/smoke_api.py [--json PATH]

Note: the smoke run applies pending migrations, the same as app startup. A
``sqlite:///`` URL whose file does not exist is refused (exit 2) before the app
is imported, so the run never creates a database.

Exit codes: 0 all good, 1 at least one failure, 2 cannot run (missing sqlite
file, 0 or >1 users).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WINDOWS_DAYS: tuple[int, ...] = (7, 30, 60, 180)
SLOW_MS: float = 2000.0

# Routes that would call Garmin/Whoop, or are not JSON, with the reason.
SKIP_ROUTES: dict[str, str] = {
    "/api/auth/garmin/status": "live Garmin probe",
    "/api/auth/whoop/url": "OAuth route",
    "/api/auth/whoop/callback": "OAuth route",
    "/api/auth/whoop/status": "Whoop token lookup / OAuth",
    "/api/account/export": "binary ZIP download",
}
SKIP_PREFIXES: tuple[str, ...] = ("/api/sync/trigger",)

PLACEHOLDER_STRINGS: frozenset[str] = frozenset({"None", "NaN", "nan", "undefined", "null"})


@dataclass
class CheckResult:
    """One route call: status, latency, and problem flags (never the body)."""

    route: str
    window: str
    status: int | None
    ms: float
    flags: list[str] = field(default_factory=list)
    failed: bool = False
    skipped: str | None = None


def find_bad_values(node: Any) -> set[str]:
    """Walk parsed JSON; return flag names for non-finite floats and placeholder strings."""
    found: set[str] = set()
    if isinstance(node, float):
        if not math.isfinite(node):
            found.add("non-finite-number")
    elif isinstance(node, str):
        if node in PLACEHOLDER_STRINGS:
            found.add(f"placeholder-string:{node}")
    elif isinstance(node, list):
        for v in node:
            found |= find_bad_values(v)
    elif isinstance(node, dict):
        for v in node.values():
            found |= find_bad_values(v)
    return found


def sqlite_file_missing(url: str) -> str | None:
    """Return the path of a ``sqlite:///`` URL's file when it does not exist, else None."""
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return None
    db_path = parsed.database
    if not db_path or db_path == ":memory:" or Path(db_path).exists():
        return None
    return db_path


def check_response(
    route: str,
    window: str,
    status: int,
    text: str,
    ms: float,
    allowed_204: bool,
) -> CheckResult:
    """Apply the per-response checks and return a result with flags only."""
    res = CheckResult(route=route, window=window, status=status, ms=round(ms, 1))
    ok_status = status == 200 or (status == 204 and allowed_204)
    if not ok_status:
        res.flags.append(f"status-{status}")
        res.failed = True
    if status == 204 and allowed_204:
        return res
    try:
        parsed = json.loads(text)
    except ValueError:
        res.flags.append("invalid-json")
        res.failed = True
        parsed = None
    if parsed is not None and ok_status:
        for name in sorted(find_bad_values(parsed)):
            res.flags.append(name)
            res.failed = True
    if ms > SLOW_MS:
        res.flags.append("slow")
    return res


def _window(days: int, today: date) -> dict[str, str]:
    return {"start": (today - timedelta(days=days)).isoformat(), "end": today.isoformat()}


def discover_routes(app: Any) -> dict[str, dict[str, Any]]:
    """Return ``{path: {"params": {name: required}, "204": bool}}`` for GET /api routes."""
    routes: dict[str, dict[str, Any]] = {}
    for path, item in sorted(app.openapi()["paths"].items()):
        op = item.get("get")
        if op is None or not path.startswith("/api/"):
            continue
        routes[path] = {
            "params": {p["name"]: bool(p.get("required")) for p in op.get("parameters", [])},
            "204": "204" in op.get("responses", {}),
        }
    return routes


def run_smoke(client: Any, headers: dict[str, str], today: date | None = None) -> list[CheckResult]:
    """Smoke every discoverable GET route with ``client``; return one result per call."""
    from src.analytics.trends import _METRIC_SOURCE, _SPECIAL_METRICS  # noqa: PLC0415

    today = today or date.today()
    metrics = sorted(set(_METRIC_SOURCE) | _SPECIAL_METRICS)
    results: list[CheckResult] = []

    def call(route: str, url: str, params: dict[str, str], label: str, a204: bool) -> Any:
        t0 = time.perf_counter()
        r = client.get(url, params=params, headers=headers)
        ms = (time.perf_counter() - t0) * 1000
        results.append(check_response(route, label, r.status_code, r.text, ms, a204))
        return r

    # Real workout ids (up to 3, plus one strength workout) for id routes.
    wk_ids: list[str] = []
    strength_id: str | None = None
    r = client.get("/api/workouts", params=_window(180, today), headers=headers)
    if r.status_code == 200:
        rows = r.json()
        wk_ids = [str(w["id"]) for w in rows[-3:]]
        strength = [w for w in rows if "strength" in (w.get("activity_type") or "").lower()]
        if strength:
            strength_id = str(strength[-1]["id"])
            if strength_id not in wk_ids:
                wk_ids = wk_ids[:2] + [strength_id]

    for path, meta in discover_routes(client.app).items():
        if path in SKIP_ROUTES or path.startswith(SKIP_PREFIXES):
            results.append(
                CheckResult(path, "-", None, 0.0, skipped=SKIP_ROUTES.get(path, "sync trigger"))
            )
            continue
        params, a204 = meta["params"], meta["204"]
        placeholders = re.findall(r"\{(\w+)\}", path)
        base_params = {k for k in params if k not in placeholders}
        if "metric" in placeholders:
            variants = [(m, {"metric": m}) for m in metrics]
        elif "workout_id" in placeholders:
            ids: list[str] = list(wk_ids)
            if path.endswith(("/exercise-summary", "/exercise-sets")) and strength_id:
                ids = [strength_id] + [i for i in ids if i != strength_id][:2]
            if not ids:
                results.append(CheckResult(path, "-", None, 0.0, skipped="no workout ids"))
                continue
            variants = [(f"id#{i + 1}", {"workout_id": w}) for i, w in enumerate(ids)]
        elif placeholders:
            results.append(CheckResult(path, "-", None, 0.0, skipped="unsupported path param"))
            continue
        else:
            variants = [("-", {})]

        for vlabel, pathvars in variants:
            url = path
            for k, v in pathvars.items():
                url = url.replace("{" + k + "}", v)
            one_day = next((k for k in ("end", "date") if k in base_params), None)
            if {"start", "end"} <= base_params or "days" in base_params:
                for d in WINDOWS_DAYS:
                    lab = f"{vlabel}/{d}d" if vlabel != "-" else f"{d}d"
                    qp = _window(d, today) if "start" in base_params else {"days": str(d)}
                    call(path, url, qp, lab, a204)
            elif one_day:
                lab = vlabel if vlabel != "-" else "today"
                call(path, url, {one_day: today.isoformat()}, lab, a204)
            else:
                call(path, url, {}, vlabel, a204)
    return results


def format_table(results: list[CheckResult]) -> str:
    """Render results as a fixed-width table."""
    w = max((len(r.route) for r in results), default=10)
    lines = [f"{'ROUTE':<{w}}  {'WINDOW':<18} {'STATUS':>6} {'MS':>8}  FLAGS"]
    for r in results:
        if r.skipped:
            lines.append(f"{r.route:<{w}}  {'-':<18} {'skip':>6} {'':>8}  {r.skipped}")
            continue
        lines.append(
            f"{r.route:<{w}}  {r.window:<18} {r.status!s:>6} {r.ms:>8.1f}  {','.join(r.flags)}"
        )
    return "\n".join(lines)


def summarize(results: list[CheckResult]) -> str:
    """Return a failure/flag summary block."""
    ran = [r for r in results if not r.skipped]
    failures = [r for r in ran if r.failed]
    slow = [r for r in ran if "slow" in r.flags and not r.failed]
    out = [
        f"calls={len(ran)} skipped={len(results) - len(ran)} "
        f"failures={len(failures)} slow-only={len(slow)}"
    ]
    for r in failures + slow:
        out.append(f"  {'FAIL' if r.failed else 'SLOW'} {r.route} [{r.window}] {','.join(r.flags)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description="In-process API smoke check.")
    ap.add_argument("--json", metavar="PATH", help="write results (statuses/flags only)")
    args = ap.parse_args(argv)

    from config.settings import settings  # noqa: PLC0415

    url = settings.database_url
    print(f"DATABASE_URL={make_url(url).render_as_string(hide_password=True)}")
    missing = sqlite_file_missing(url)
    if missing is not None:
        print(f"error: sqlite file {missing} does not exist; refusing to create it.")
        return 2

    with patch("src.api.main.start_scheduler"), patch("src.api.main.stop_scheduler"):
        from fastapi.testclient import TestClient  # noqa: PLC0415  # pyright: ignore[reportMissingImports]

        from src.api.dependencies import get_engine_dep  # noqa: PLC0415
        from src.api.main import app  # noqa: PLC0415
        from src.auth.security import create_access_token  # noqa: PLC0415
        from src.database.owner import get_owner_user_id  # noqa: PLC0415

        try:
            owner = get_owner_user_id(get_engine_dep())
        except RuntimeError:
            print("error: more than one user in this database; smoke needs exactly one.")
            return 2
        if owner is None:
            print("error: no users in this database; smoke needs exactly one owner.")
            return 2
        token, _ = create_access_token(owner)
        headers = {"Authorization": f"Bearer {token}"}
        with TestClient(app) as client:
            results = run_smoke(client, headers)

    print(format_table(results))
    print()
    print(summarize(results))
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(r) for r in results], indent=1))
    return 1 if any(r.failed for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
