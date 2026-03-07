"""Workouts API routes."""

import dataclasses
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from src.analytics.workout_analysis import (
    get_enriched_workout,
    get_enriched_workouts,
    get_workout_type_summary,
)
from src.api.dependencies import get_engine_dep
from src.api.models import EnrichedWorkoutResponse, WorkoutTypeSummaryItem

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
    "",
    response_model=list[EnrichedWorkoutResponse],
    summary="List enriched workouts",
)
async def list_workouts(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: date = Query(..., description="End date (YYYY-MM-DD)"),
    engine: Engine = Depends(get_engine_dep),
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
    "/{workout_id}",
    response_model=EnrichedWorkoutResponse,
    summary="Single workout detail",
)
async def get_workout(
    workout_id: str,
    engine: Engine = Depends(get_engine_dep),
) -> EnrichedWorkoutResponse:
    """Return a single enriched workout by its unified_workouts ID."""
    try:
        workout = get_enriched_workout(engine, workout_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if workout is None:
        raise HTTPException(status_code=404, detail=f"Workout '{workout_id}' not found")
    return EnrichedWorkoutResponse(**dataclasses.asdict(workout))
