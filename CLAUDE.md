# Fitness Dashboard — Claude Code Context

## Project
Personal training dashboard integrating Garmin + Whoop data into a single view.
Python + FastAPI + SQLite + Streamlit (migrating to React later).

## Reference Docs
Full project planning docs are in opus_plan_src_files/. Read these when you need:
- Architecture and data flow → Technical_Design_Doc.md
- Database schema (exact table definitions) → Technical_Design_Doc.md Section 3
- Task details and acceptance criteria → Phase_Task_Breakdowns.md
- Overall roadmap and priorities → Garmin_Whoop_Dashboard_Roadmap_v2.md

## Current Phase
Phase 1 — Whoop Proof of Concept
Current task: 1.2

## Key Decisions
- Whoop = source of truth for recovery, sleep quality, body vitals
- Garmin = source of truth for workout detail, running dynamics
- Deduplication by timestamp + duration only
- Store raw API responses in raw_json column for reprocessing
- Docker comes at end of Phase 1, not day one

## Conventions
- Python 3.11+
- Type hints on all functions
- Docstrings on public functions
- Tests in tests/ using pytest
- Secrets in .env, never hardcoded
- Always use the venv environment

## Notes
(Add stuff here as you learn things — what worked, what didn't, gotchas, etc.)