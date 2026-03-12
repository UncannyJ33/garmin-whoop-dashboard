# ── Stage 1: Build React frontend ────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend-react

# Install deps first for better layer caching
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci --silent

# Copy source and build
COPY frontend-react/ ./
RUN npm run build

# ── Stage 2: Python backend ───────────────────────────────────────────────────
FROM python:3.11-slim

# Install uv
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install Python deps first for better layer caching.
# uv sync creates a .venv at /app/.venv — add it to PATH so executables are reachable.
ENV PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./

# Install deps only (not the project itself) — cached unless pyproject.toml/uv.lock changes
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code (changes more often than deps)
COPY src/ ./src/
COPY frontend/ ./frontend/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Install the project package itself (fast: deps already in place)
RUN uv sync --frozen --no-dev

# Copy the built React app — FastAPI serves it as static files
COPY --from=frontend-builder /app/frontend-react/dist ./frontend-react/dist

# Ensure the data directory exists; in practice it's overridden by the volume mount
RUN mkdir -p data

EXPOSE 8000
