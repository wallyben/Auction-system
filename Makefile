PYTHON ?= python3
export DATABASE_URL ?= postgresql+psycopg://arie:arie@localhost:5432/arie

.PHONY: dev test test-live scan scan-source validate production-proof migrate install db-check ebay-check ebay-notification-check ebay-notification-token ebay-notification-show-token ebay-notification-watch ebay-notification-set-endpoint ebay-notification-proof ebay-notification-activate ebay-notification-await ebay-owner-oauth-url ebay-owner-ingest source-health backtest

install:
	$(PYTHON) -m pip install -e ".[dev]"

migrate:
	$(PYTHON) -m alembic upgrade head

db-check:
	$(PYTHON) -m app.cli db-check

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

ebay-notification-check:
	$(PYTHON) -m app.cli ebay-notification-check

ebay-notification-token:
	$(PYTHON) -m app.cli ebay-notification-token

ebay-notification-show-token:
	$(PYTHON) -m app.cli ebay-notification-show-token

ebay-notification-watch:
	$(PYTHON) -m app.cli ebay-notification-watch

ebay-notification-set-endpoint:
	$(PYTHON) -m app.cli ebay-notification-set-endpoint $(URL)

ebay-notification-proof:
	$(PYTHON) -m app.cli ebay-notification-proof

ebay-notification-activate:
	$(PYTHON) -m app.cli ebay-notification-activate

ebay-notification-await:
	$(PYTHON) -m app.cli ebay-notification-await

ebay-owner-oauth-url:
	$(PYTHON) -m app.cli ebay-owner-oauth-url

ebay-owner-ingest:
	$(PYTHON) -m app.cli ebay-owner-ingest

source-health:
	$(PYTHON) -m app.cli source-health

backtest:
	$(PYTHON) -m app.cli backtest

revalue:
	$(PYTHON) -m app.cli revalue
