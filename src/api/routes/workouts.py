"""Workouts API routes."""

import dataclasses
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine, text

from src.analytics.workout_analysis import (
    get_enriched_workout,
    get_enriched_workouts,
    get_workout_type_summary,
)
from src.api.dependencies import get_engine_dep
from src.api.models import (
    EnrichedWorkoutResponse,
    ExerciseSetItem,
    StrengthMaxWeightItem,
    StrengthVolumeItem,
    WorkoutTypeSummaryItem,
)
from src.auth.dependencies import get_current_user
from src.auth.models import User

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


@router.get(
    "/summary",
    response_model=list[WorkoutTypeSummaryItem],
    summary="Activity type summary",
)
async def workout_summary(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    _user: User = Depends(get_current_user),
) -> list[WorkoutTypeSummaryItem]:
    """Aggregate stats grouped by activity type for the given date range."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    try:
        summary = get_workout_type_summary(engine, start, end)
        return [
            WorkoutTypeSummaryItem(activity_type=atype, **stats)
            for atype, stats in sorted(summary.items(), key=lambda x: -x[1]["count"])
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/strength-volume",
    response_model=list[StrengthVolumeItem],
    summary="Total volume per strength session",
)
async def strength_volume(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[StrengthVolumeItem]:
    """Return total volume (kg × reps) per strength session date in range."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT
                    uw.date,
                    SUM(es.repetition_count * es.weight_kg) AS total_volume_kg
                FROM unified_workouts uw
                JOIN garmin_exercise_sets es ON es.activity_id = uw.garmin_activity_id
                WHERE uw.date BETWEEN :start AND :end
                  AND uw.user_id = :uid
                  AND es.set_type = 'ACTIVE'
                  AND es.repetition_count IS NOT NULL
                  AND es.weight_kg IS NOT NULL
                  AND es.weight_kg > 0
                GROUP BY uw.date
                ORDER BY uw.date
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
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    current_user: User = Depends(get_current_user),
) -> list[StrengthMaxWeightItem]:
    """Return max weight (kg) per tracked exercise per session date in range."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text("""
                SELECT
                    uw.date,
                    es.exercise_name,
                    MAX(es.weight_kg) AS max_weight_kg
                FROM unified_workouts uw
                JOIN garmin_exercise_sets es ON es.activity_id = uw.garmin_activity_id
                WHERE uw.date BETWEEN :start AND :end
                  AND uw.user_id = :uid
                  AND es.set_type = 'ACTIVE'
                  AND es.weight_kg IS NOT NULL
                  AND es.weight_kg > 0
                  AND es.exercise_name IS NOT NULL
                GROUP BY uw.date, es.exercise_name
                ORDER BY uw.date, es.exercise_name
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
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
    _user: User = Depends(get_current_user),
) -> list[EnrichedWorkoutResponse]:
    """Return all enriched workouts in the date range, sorted by date ascending."""
    if start > end:
        raise HTTPException(status_code=400, detail="start must be ≤ end")
    try:
        workouts = get_enriched_workouts(engine, start, end)
        return [EnrichedWorkoutResponse(**dataclasses.asdict(w)) for w in workouts]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/{workout_id}/exercise-sets",
    response_model=list[ExerciseSetItem],
    summary="Exercise sets for a strength workout",
)
async def get_exercise_sets(
    workout_id: str,
    engine: Engine = Depends(get_engine_dep),
    _user: User = Depends(get_current_user),
) -> list[ExerciseSetItem]:
    """Return active exercise sets for a unified workout (strength only)."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT garmin_activity_id FROM unified_workouts WHERE id = :id"),
            {"id": workout_id},
        ).one_or_none()
    if row is None or row[0] is None:
        return []
    garmin_id = row[0]
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
    _user: User = Depends(get_current_user),
) -> EnrichedWorkoutResponse:
    """Return a single enriched workout by its unified_workouts ID."""
    try:
        workout = get_enriched_workout(engine, workout_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if workout is None:
        raise HTTPException(status_code=404, detail=f"Workout '{workout_id}' not found")
    return EnrichedWorkoutResponse(**dataclasses.asdict(workout))
