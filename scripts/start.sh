#!/bin/sh
set -e

echo "Running database migrations..."
python -c "from src.database.migrations import run; run()"
echo "Migrations complete. Starting server on port ${PORT:-8000}..."

exec uvicorn src.api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
