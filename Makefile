PYTHON    = .venv/bin/python
UVICORN   = .venv/bin/uvicorn
PYTEST    = .venv/bin/pytest
RUFF      = .venv/bin/ruff

.PHONY: run dev run-api build-frontend up down run-sync test lint fmt owner backfill

# Bind host is BIND_HOST (not HOST: zsh sets HOST to the machine hostname).
# Default is localhost-only; LAN exposure is an explicit opt-in: make run BIND_HOST=0.0.0.0
BIND_HOST ?= 127.0.0.1
PORT      ?= 8001

FRONTEND_SRC = $(shell find frontend-react/src frontend-react/public -type f)

# npm ci wipes node_modules, so only run it when the lockfile changes.
frontend-react/node_modules/.package-lock.json: frontend-react/package-lock.json
	cd frontend-react && npm ci --silent

frontend-react/dist/index.html: $(FRONTEND_SRC) frontend-react/index.html \
		frontend-react/vite.config.ts frontend-react/tailwind.config.js \
		frontend-react/postcss.config.js $(wildcard frontend-react/tsconfig*.json) \
		frontend-react/package.json frontend-react/node_modules/.package-lock.json
	cd frontend-react && npm run build

build-frontend: frontend-react/dist/index.html

run: frontend-react/dist/index.html
	@if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:$(PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "Port $(PORT) is in use (try: make run PORT=8002; also set WHOOP_REDIRECT_URI to match)"; exit 1; fi
	@echo "Open http://localhost:$(PORT)"
	$(UVICORN) src.api.main:app --host $(BIND_HOST) --port $(PORT)

dev:
	$(UVICORN) src.api.main:app --port $(PORT) --reload

run-api: dev

up:
	docker compose up -d --build

down:
	docker compose down

run-sync:
	$(PYTHON) scripts/initial_sync.py

test:
	$(PYTEST) -q

lint:
	$(RUFF) check .

fmt:
	$(RUFF) format .

owner:
	$(PYTHON) scripts/create_owner.py --email $(EMAIL)

backfill:
	$(if $(START),,$(error START=YYYY-MM-DD is required))
	PORT=$(PORT) $(shell command -v caffeinate >/dev/null && echo caffeinate -i) $(PYTHON) scripts/backfill.py --source $(or $(SOURCE),all) --start $(START) $(if $(CHUNK_DAYS),--chunk-days $(CHUNK_DAYS),) $(if $(FORCE),--force,)
