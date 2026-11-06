# ── Stage 1: Build React frontends ───────────────────────────────────────────
FROM node:20-slim AS frontend-builder

# Build main React app
WORKDIR /app/frontend-react
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci --silent
COPY frontend-react/ ./
RUN npm run build

# Build pulse-demo (interactive demo)
RUN npm install -g pnpm --silent
WORKDIR /app/pulse-demo
COPY pulse-demo/package.json pulse-demo/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --silent
COPY pulse-demo/ ./
RUN pnpm exec vite build

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
COPY config/ ./config/
COPY --chmod=0755 scripts/ ./scripts/

# Install the project package itself (fast: deps already in place)
RUN uv sync --frozen --no-dev

# Copy the built React app — FastAPI serves it as static files
COPY --from=frontend-builder /app/frontend-react/dist ./frontend-react/dist

# Merge pulse-demo into the React dist under /demo — SPA fallback serves it
COPY --from=frontend-builder /app/pulse-demo/dist ./frontend-react/dist/demo

# Ensure the data directory exists; in practice it's overridden by the volume mount
RUN mkdir -p data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request, os; urllib.request.urlopen(f\"http://localhost:{os.getenv('PORT', '8000')}/api/health\")" || exit 1

CMD ["scripts/start.sh"]
