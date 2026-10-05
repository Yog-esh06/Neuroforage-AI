# NeuroForge AI — developer commands.  Windows users: run these from Git Bash, or copy the commands.
PY ?= .venv/Scripts/python
ifeq ($(OS),Windows_NT)
else
PY = .venv/bin/python
endif

.PHONY: help setup sample backend worker frontend test test-fast eval migrate migration docker-up docker-down typecheck verify-worker verify-postgres clean

help:
	@echo "setup       create venv + install backend deps (+ spaCy model) and frontend deps"
	@echo "sample      generate the sample corpus in data/sample"
	@echo "backend     run the API (SQLite, inline jobs) on :8000"
	@echo "worker      run a Celery worker (needs Redis; set JOB_BACKEND=celery)"
	@echo "frontend    run the Next.js dev server on :3000"
	@echo "test        run the full backend test suite"
	@echo "test-fast   skip slow OCR / full-pipeline tests"
	@echo "eval        run the evaluation framework on the sample corpus"
	@echo "migrate     alembic upgrade head"
	@echo "verify-worker    prove a real Celery worker consumes an upload (Redis-free filesystem broker)"
	@echo "verify-postgres  run the Alembic migration + API/integration tests on embedded PostgreSQL"
	@echo "docker-up   docker compose up --build"

setup:
	python -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m spacy download en_core_web_sm
	cd frontend && npm install

sample:
	$(PY) backend/scripts/generate_sample_data.py

backend:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

worker:
	cd backend && ../$(PY) -m celery -A app.workers.celery_app.celery_app worker -l info -Q ingestion,analysis -c 2

frontend:
	cd frontend && npm run dev

test:
	$(PY) -m pytest

test-fast:
	$(PY) -m pytest -m "not slow"

eval:
	cd backend && ../$(PY) -m app.ai.evaluation.runner

migrate:
	$(PY) -m alembic upgrade head

migration:
	$(PY) -m alembic revision --autogenerate -m "$(m)"

typecheck:
	cd frontend && npm run typecheck

verify-worker:
	$(PY) backend/scripts/verify_worker.py

verify-postgres:
	$(PY) backend/scripts/verify_postgres.py

docker-up:
	docker compose up --build

docker-down:
	docker compose down

clean:
	rm -rf storage/neuroforge.db* storage/documents/* data/processed/*.json
