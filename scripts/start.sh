#!/bin/sh
set -e

echo "Running database migrations..."
python -c "from src.database.migrations import run; run()"
echo "Migrations complete."

# Reset PostgreSQL sequences to avoid primary-key conflicts when rows were
# inserted with explicit IDs (e.g. during migrations on a fresh DB).
# This is a no-op on SQLite.
python -c "
from config.settings import settings
if not settings.database_url.startswith('sqlite'):
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.database_url)
    tables = ['sync_log', 'garmin_exercise_sets']
    with engine.begin() as conn:
        for t in tables:
            conn.execute(text(
                f\"SELECT setval(pg_get_serial_sequence('{t}', 'id'), \"
                f\"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)\"
            ))
    print('Sequences reset.')
"

echo "Starting server on port ${PORT:-8000}..."

exec uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
