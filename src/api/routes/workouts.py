"""Workouts API routes."""

import dataclasses
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, text

from src.analytics.workout_analysis import (
    get_enriched_workout,
    get_enriched_workouts,
    get_workout_type_summary,
)
from src.api.dependencies import DateRangeParams, get_engine_dep
from src.api.models import (
    EnrichedWorkoutResponse,
    ExerciseSetItem,
    ExerciseSummaryItem,
    StrengthMaxWeightItem,
    StrengthVolumeItem,
    WorkoutTypeSummaryItem,
)
from src.auth.dependencies import get_current_user
from src.auth.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


def _garmin_activity_id(engine: Engine, workout_id: str, user_id: str) -> str | None:
    """Return the Garmin activity id for one of the user's unified workouts, or None."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT garmin_activity_id FROM unified_workouts WHERE id = :id AND user_id = :uid"
            ),
            {"id": workout_id, "uid": user_id},
        ).one_or_none()
    return None if row is None else row[0]


@router.get(
    "/summary",
    response_model=list[WorkoutTypeSummaryItem],
    summary="Activity type summary",
)
async def workout_summary(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[WorkoutTypeSummaryItem]:
    """Aggregate stats grouped by activity type for the given date range."""
    start, end = dates.validated()
    try:
        summary = get_workout_type_summary(engine, start, end, user_id=current_user.id)
        return [
            WorkoutTypeSummaryItem(activity_type=atype, **stats)
            for atype, stats in sorted(summary.items(), key=lambda x: -x[1]["count"])
        ]
    except Exception as exc:
        logger.exception("workout_summary failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/strength-volume",
    response_model=list[StrengthVolumeItem],
    summary="Total volume per strength session",
)
async def strength_volume(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[StrengthVolumeItem]:
    """Return total volume (kg × reps) per strength session date in range."""
    start, end = dates.validated()
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT date, SUM(v) AS total_volume_kg FROM (
                    SELECT uw.date AS date, SUM(es.repetition_count * es.weight_kg) AS v
                    FROM unified_workouts uw
                    JOIN garmin_exercise_sets es ON es.activity_id = uw.garmin_activity_id
                    WHERE uw.date BETWEEN :start AND :end
                      AND uw.user_id = :uid
                      AND es.set_type = 'ACTIVE'
                      AND es.repetition_count IS NOT NULL
                      AND es.weight_kg IS NOT NULL
                      AND es.weight_kg > 0
                    GROUP BY uw.date
                    UNION ALL
                    SELECT uw.date AS date, SUM(s.volume_kg) AS v
                    FROM unified_workouts uw
                    JOIN garmin_exercise_summaries s ON s.activity_id = uw.garmin_activity_id
                    WHERE uw.date BETWEEN :start AND :end
                      AND uw.user_id = :uid
                      AND s.volume_kg IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM garmin_exercise_sets es
                          WHERE es.activity_id = uw.garmin_activity_id
                            AND es.set_type = 'ACTIVE'
                      )
                    GROUP BY uw.date
                ) AS u
                GROUP BY date
                ORDER BY date
            """),
                {"start": str(start), "end": str(end), "uid": current_user.id},
            )
            .mappings()
            .all()
        )
    return [StrengthVolumeItem(date=r["date"], total_volume_kg=r["total_volume_kg"]) for r in rows]


@router.get(
    "/strength-max-weight",
    response_model=list[StrengthMaxWeightItem],
    summary="Max weight per tracked exercise per session",
)
async def strength_max_weight(
    dates: DateRangeParams = Depends(),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[StrengthMaxWeightItem]:
    """Return max weight (kg) per tracked exercise per session date in range."""
    start, end = dates.validated()
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT date, exercise_name, MAX(w) AS max_weight_kg FROM (
                    SELECT uw.date AS date, es.exercise_name AS exercise_name,
                           MAX(es.weight_kg) AS w
                    FROM unified_workouts uw
                    JOIN garmin_exercise_sets es ON es.activity_id = uw.garmin_activity_id
                    WHERE uw.date BETWEEN :start AND :end
                      AND uw.user_id = :uid
                      AND es.set_type = 'ACTIVE'
                      AND es.weight_kg IS NOT NULL
                      AND es.weight_kg > 0
                      AND es.exercise_name IS NOT NULL
                    GROUP BY uw.date, es.exercise_name
                    UNION ALL
                    SELECT uw.date AS date, s.exercise_name AS exercise_name,
                           MAX(s.max_weight_kg) AS w
                    FROM unified_workouts uw
                    JOIN garmin_exercise_summaries s ON s.activity_id = uw.garmin_activity_id
                    WHERE uw.date BETWEEN :start AND :end
                      AND uw.user_id = :uid
                      AND s.max_weight_kg IS NOT NULL
                      AND s.max_weight_kg > 0
                      AND s.exercise_name IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM garmin_exercise_sets es
                          WHERE es.activity_id = uw.garmin_activity_id
                            AND es.set_type = 'ACTIVE'
                      )
                    GROUP BY uw.date, s.exercise_name
                ) AS u
                GROUP BY date, exercise_name
                ORDER BY date, exercise_name
            """),
                {"start": str(start), "end": str(end), "uid": current_user.id},
            )
            .mappings()
            .all()
        )
    return [
        StrengthMaxWeightItem(
            date=r["date"],
            exercise_name=r["exercise_name"],
            max_weight_kg=r["max_weight_kg"],
        )
        for r in rows
    ]


@router.get(
    "",
    response_model=list[EnrichedWorkoutResponse],
    summary="List enriched workouts",
)
async def list_workouts(
    dates: DateRangeParams = Depends(),
    limit: int | None = Query(
        None, ge=1, le=500, description="Max workouts to return (omit for all)"
    ),
    offset: int = Query(0, ge=0, description="Number of workouts to skip"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[EnrichedWorkoutResponse]:
    """Return enriched workouts in the date range, sorted by date ascending.

    Supports optional server-side pagination via limit/offset. When limit is
    omitted, all workouts in the range are returned (backward compatible).
    The total count is always returned in the X-Total-Count response header.
    """
    start, end = dates.validated()
    try:
        workouts = get_enriched_workouts(
            engine,
            start,
            end,
            user_id=current_user.id,
            limit=limit,
            offset=offset,
        )
        return [EnrichedWorkoutResponse(**dataclasses.asdict(w)) for w in workouts]
    except Exception as exc:
        logger.exception("list_workouts failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{workout_id}/exercise-sets",
    response_model=list[ExerciseSetItem],
    summary="Exercise sets for a strength workout",
)
async def get_exercise_sets(
    workout_id: str,
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[ExerciseSetItem]:
    """Return active exercise sets for a unified workout (strength only)."""
    garmin_id = _garmin_activity_id(engine, workout_id, current_user.id)
    if garmin_id is None:
        return []
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT set_order, exercise_category, exercise_name,
                       repetition_count, weight_kg, duration_seconds
                FROM garmin_exercise_sets
                WHERE activity_id = :aid AND set_type = 'ACTIVE'
                ORDER BY set_order
            """),
                {"aid": garmin_id},
            )
            .mappings()
            .all()
        )
    return [ExerciseSetItem(**dict(r)) for r in rows]


@router.get(
    "/{workout_id}",
    response_model=EnrichedWorkoutResponse,
    summary="Single workout detail",
)
async def get_workout(
    workout_id: str,
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> EnrichedWorkoutResponse:
    """Return a single enriched workout by its unified_workouts ID."""
    try:
        workout = get_enriched_workout(engine, workout_id, user_id=current_user.id)
    except Exception as exc:
        logger.exception("get_workout failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if workout is None:
        raise HTTPException(status_code=404, detail=f"Workout '{workout_id}' not found")
    return EnrichedWorkoutResponse(**dataclasses.asdict(workout))


@router.get(
    "/{workout_id}/exercise-summary",
    response_model=list[ExerciseSummaryItem],
    summary="Per-exercise summary for a strength workout",
)
async def get_exercise_summary(
    workout_id: str,
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[ExerciseSummaryItem]:
    """Return per-exercise summaries (Personal API) for a unified workout."""
    garmin_id = _garmin_activity_id(engine, workout_id, current_user.id)
    if garmin_id is None:
        return []
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT exercise_category, exercise_name, set_count, repetition_count,
                       volume_kg, max_weight_kg, duration_seconds
                FROM garmin_exercise_summaries
                WHERE activity_id = :aid
                ORDER BY id
            """),
                {"aid": garmin_id},
            )
            .mappings()
            .all()
        )
    return [ExerciseSummaryItem(**dict(r)) for r in rows]
