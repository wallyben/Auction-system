PYTHON ?= python3
export DATABASE_URL ?= postgresql+psycopg://arie:arie@localhost:5432/arie

.PHONY: dev test test-live scan scan-source validate production-proof migrate install ebay-check source-health backtest

install:
	$(PYTHON) -m pip install -e ".[dev]"

migrate:
	$(PYTHON) -m alembic upgrade head

dev:
	$(PYTHON) -m alembic upgrade head
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	$(PYTHON) -m pytest tests -m "not live"

test-live:
	$(PYTHON) -m pytest tests -m live -v

scan:
	$(PYTHON) -m app.cli scan

scan-source:
	$(PYTHON) -m app.cli scan-source $(SOURCE)

validate:
	$(PYTHON) -m app.cli validate

production-proof:
	$(PYTHON) -m app.cli production-proof

ebay-check:
	$(PYTHON) -m app.cli ebay-check

source-health:
	$(PYTHON) -m app.cli source-health

backtest:
	$(PYTHON) -m app.cli backtest
