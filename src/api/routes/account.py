"""Account management routes: data export and account deletion."""

import csv
import io
import logging
import zipfile
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine, text

from src.api.dependencies import get_engine_dep
from src.auth.dependencies import get_current_user
from src.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])


def _rows_to_csv(rows: list) -> str:
    """Convert a list of mapping rows to a CSV string."""
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return buf.getvalue()


@router.get(
    "/export",
    summary="Export all user data as a ZIP file containing CSV files",
)
async def export_data(
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Export the authenticated user's data as a ZIP archive.

    Returns a ZIP file containing four CSV files:
    - workouts.csv — unified workout records
    - sleep.csv — unified sleep records
    - daily_metrics.csv — unified daily summary metrics
    - recovery.csv — Whoop recovery data joined with cycle strain
    """
    uid = current_user.id

    with engine.connect() as conn:
        workouts = (
            conn.execute(
                text(
                    "SELECT * FROM unified_workouts WHERE user_id = :uid ORDER BY start_time DESC"
                ),
                {"uid": uid},
            )
            .mappings()
            .all()
        )

        sleep = (
            conn.execute(
                text("SELECT * FROM unified_sleep WHERE user_id = :uid ORDER BY date DESC"),
                {"uid": uid},
            )
            .mappings()
            .all()
        )

        daily = (
            conn.execute(
                text("SELECT * FROM unified_daily WHERE user_id = :uid ORDER BY date DESC"),
                {"uid": uid},
            )
            .mappings()
            .all()
        )

        recovery = (
            conn.execute(
                text(
                    """
                    SELECT wr.id, wr.cycle_id, wr.score_state, wr.recovery_score,
                           wr.resting_heart_rate, wr.hrv_rmssd, wr.spo2_pct,
                           wr.skin_temp_celsius, wr.fetched_at,
                           wc.start_time AS cycle_start, wc.end_time AS cycle_end,
                           wc.strain AS cycle_strain
                    FROM whoop_recovery wr
                    LEFT JOIN whoop_cycles wc ON wr.cycle_id = wc.id
                    WHERE wr.user_id = :uid
                    ORDER BY wr.fetched_at DESC
                    """
                ),
                {"uid": uid},
            )
            .mappings()
            .all()
        )

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("workouts.csv", _rows_to_csv(list(workouts)))
        zf.writestr("sleep.csv", _rows_to_csv(list(sleep)))
        zf.writestr("daily_metrics.csv", _rows_to_csv(list(daily)))
        zf.writestr("recovery.csv", _rows_to_csv(list(recovery)))

    zip_buf.seek(0)
    filename = f"pulseengine_export_{datetime.now(UTC).strftime('%Y%m%d')}.zip"
    logger.info("Data export generated for user %s", uid)
    return StreamingResponse(
        zip_buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "",
    status_code=204,
    summary="Permanently delete the authenticated user's account and all data",
)
async def delete_account(
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> None:
    """Permanently delete the user's account and all associated data.

    Deletes records from all data tables in dependency order (children before
    parents), then removes the user record itself.  This action is irreversible.
    """
    uid = current_user.id
    logger.warning("Account deletion initiated for user %s", uid)

    with engine.begin() as conn:
        # Tokens (Whoop OAuth, Garmin session, OAuth states)
        conn.execute(
            text("DELETE FROM token_store WHERE service = :whoop OR service = :garmin"),
            {"whoop": f"whoop_{uid}", "garmin": f"garmin_{uid}"},
        )
        conn.execute(
            text("DELETE FROM token_store WHERE user_id = :uid AND service LIKE 'whoop_state_%'"),
            {"uid": uid},
        )

        # Credentials
        conn.execute(text("DELETE FROM garmin_credentials WHERE user_id = :uid"), {"uid": uid})

        # Sync log
        conn.execute(text("DELETE FROM sync_log WHERE user_id = :uid"), {"uid": uid})

        # Unified tables
        conn.execute(text("DELETE FROM unified_workouts WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM unified_sleep WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM unified_daily WHERE user_id = :uid"), {"uid": uid})

        # Garmin tables (exercise_sets/summaries reference activities — delete first)
        conn.execute(text("DELETE FROM garmin_exercise_summaries WHERE user_id = :uid"), {"uid": uid})
        conn.execute(
            text(
                "DELETE FROM garmin_exercise_sets WHERE activity_id IN "
                "(SELECT activity_id FROM garmin_activities WHERE user_id = :uid)"
            ),
            {"uid": uid},
        )
        conn.execute(text("DELETE FROM garmin_activities WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM garmin_daily_summary WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM garmin_sleep WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM garmin_hrv WHERE user_id = :uid"), {"uid": uid})

        # Whoop tables (workouts/recovery/sleep reference cycles — delete first)
        conn.execute(text("DELETE FROM whoop_workouts WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM whoop_recovery WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM whoop_sleep WHERE user_id = :uid"), {"uid": uid})
        conn.execute(text("DELETE FROM whoop_cycles WHERE app_user_id = :uid"), {"uid": uid})

        # User record last
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    logger.info("Account deletion complete for user %s", uid)
