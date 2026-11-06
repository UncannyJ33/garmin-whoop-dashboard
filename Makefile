PYTHON    = .venv/bin/python
UVICORN   = .venv/bin/uvicorn
STREAMLIT = .venv/bin/streamlit
PYTEST    = .venv/bin/pytest
RUFF      = .venv/bin/ruff

.PHONY: run-api run-frontend run-sync test lint fmt owner

run-api:
	$(UVICORN) src.api.main:app --port 8000 --reload

run-frontend:
	$(STREAMLIT) run frontend/app.py

run-sync:
	$(PYTHON) scripts/initial_sync.py

test:
	$(PYTEST) tests/ -v

lint:
	$(RUFF) check .

fmt:
	$(RUFF) format .

owner:
	$(PYTHON) scripts/create_owner.py --email $(EMAIL)
