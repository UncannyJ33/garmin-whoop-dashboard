#!/bin/sh
set -e

echo "Running database migrations..."
python -c "
from config.settings import settings
from src.database.migrations import run

# Use a single connection for all startup tasks to minimise pooler load.
kwargs = {}
if not settings.database_url.startswith('sqlite'):
    from sqlalchemy import create_engine
    engine = create_engine(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=30,
        connect_args={'sslmode': 'require'},
    )
    kwargs['engine'] = engine
run(**kwargs)

# Reset PostgreSQL sequences to avoid primary-key conflicts when rows were
# inserted with explicit IDs (e.g. during migrations on a fresh DB).
if not settings.database_url.startswith('sqlite'):
    from sqlalchemy import text
    tables = ['sync_log', 'garmin_exercise_sets']
    with engine.begin() as conn:
        for t in tables:
            conn.execute(text(
                f\"SELECT setval(pg_get_serial_sequence('{t}', 'id'), \"
                f\"COALESCE((SELECT MAX(id) FROM {t}), 0) + 1, false)\"
            ))
    print('Sequences reset.')

engine.dispose()
"
echo "Startup DB tasks complete."

echo "Starting server on port ${PORT:-8000}..."

exec uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
