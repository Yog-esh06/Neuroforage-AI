# Deployment

Nothing in the business logic assumes an infrastructure vendor: database, queue, object storage and LLM are selected by
environment variables.

## Local, no Docker

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"     # Windows;  .venv/bin/python on macOS/Linux
python -m spacy download en_core_web_sm                                      # optional statistical NER
cd backend && ../.venv/Scripts/python -m uvicorn app.main:app --port 8000    # SQLite + inline jobs, tables auto-created
cd frontend && npm install && npm run dev                                    # http://localhost:3000
```

Log in with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` (defaults in `.env.example`; change them).

## Docker Compose

```bash
cp .env.example .env     # set JWT_SECRET, SEED_ADMIN_PASSWORD, POSTGRES_PASSWORD, optional LLM_*
docker compose up --build
```

| Service | Role |
|---|---|
| `postgres` | system of record (migrations applied by the backend on start) |
| `redis` | Celery broker/result backend |
| `backend` | FastAPI on :8000 (`alembic upgrade head` then uvicorn) |
| `worker` | Celery worker consuming `ingestion`, `analysis` queues |
| `frontend` | Next.js standalone server on :3000 |
| `nginx` (profile `proxy`) | optional single-origin reverse proxy on :8080 |

The `storage` volume is shared by backend and worker. For multi-host deployments use `STORAGE_BACKEND=s3`.

## Object storage

`STORAGE_BACKEND=local` (default) or `s3` with `S3_BUCKET`, `S3_ENDPOINT_URL` (MinIO/R2/Wasabi …), credentials. Both
implement `utils/storage.StorageBackend`; PDFs are streamed to a temp file when a real path is required.

## Frontend → Vercel

Deploy `frontend/` as a Vercel project (framework: Next.js). Set `NEXT_PUBLIC_API_URL` to the public backend URL and add the
Vercel origin to the backend's `CORS_ORIGINS`. The browser talks to the API directly with the user JWT.

## Backend → Render / Railway / AWS / Azure

Build from `deployment/Dockerfile.backend` (context = repo root). Required environment: `APP_ENV=production`,
`DATABASE_URL` (managed PostgreSQL), `JWT_SECRET`, `SEED_ADMIN_PASSWORD`, `CORS_ORIGINS`, and — if using background workers —
`JOB_BACKEND=celery` + `REDIS_URL`.

| Platform | Sketch |
|---|---|
| Render | Web Service (Docker) + Render PostgreSQL + Render Key Value; a second Background Worker service with the Celery start command |
| Railway | Service from Dockerfile + PostgreSQL + Redis plugins; add a worker service with the Celery command |
| AWS | ECS Fargate (API + worker task definitions) + RDS PostgreSQL + ElastiCache + S3 (`STORAGE_BACKEND=s3`), ALB with 300 s idle timeout |
| Azure | Container Apps (API + worker) + Azure Database for PostgreSQL + Azure Cache for Redis + S3-compatible storage (or MinIO) |

Run **one** instance of the API per process-local index, or accept per-replica rebuild after each ingestion (see
architecture.md → Scaling limits). `GET /api/v1/health` is the liveness/readiness probe (checks DB, and Redis when
`JOB_BACKEND=celery`).

## Migrations

`alembic upgrade head` (reads `DATABASE_URL`). In `APP_ENV=production` the app does **not** auto-create tables.
Create new migrations with `make migration m="describe change"`.

## Upgrading the embedding model

Set `EMBEDDING_BACKEND=sbert` (and install the extra), restart, then run
`python -c "from app.workers.embedding_tasks import reembed_all; print(reembed_all())"` (or enqueue `reembed_all_task`).
Vectors are tagged with the model name; only vectors of the active model are searched.
