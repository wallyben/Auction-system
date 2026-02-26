# ARIE Backend - Phase 1 Scaffold

Production-ready FastAPI scaffold for **ARIE (Automated Reseller Intelligence Engine)**.

## Stack

- Python 3.11
- FastAPI
- SQLAlchemy 2.0
- Alembic
- PostgreSQL
- Docker / Docker Compose
- Pytest

## Project Structure

```text
.
├── app
│   ├── api
│   │   └── routes
│   │       └── health.py
│   ├── core
│   │   └── config.py
│   ├── db
│   │   ├── base.py
│   │   └── session.py
│   ├── models
│   │   └── auction_lot.py
│   └── main.py
├── alembic
│   ├── env.py
│   ├── script.py.mako
│   └── versions
│       └── 20260223_0001_create_auction_lots_table.py
├── tests
│   └── test_health.py
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## Environment

Set `DATABASE_URL` for any database operation outside Docker:

```bash
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/arie"
```

## Run with Docker Compose (recommended)

```bash
docker compose up --build
```

This starts:

- `db` (PostgreSQL 16)
- `app` (FastAPI at `http://localhost:8000`)

The app container runs migrations automatically before starting Uvicorn.

Health check:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Stop services:

```bash
docker compose down -v
```

## Run locally without Docker

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
export DATABASE_URL="postgresql+psycopg://postgres:postgres@localhost:5432/arie"
alembic upgrade head
uvicorn app.main:app --reload
```

## Run tests

```bash
pytest
```