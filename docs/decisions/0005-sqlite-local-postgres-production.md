# ADR 0005 — SQLite for zero-setup local runs, PostgreSQL for Docker/production

**Status:** accepted

## Decision
All models use portable SQLAlchemy types (`JSON`, `LargeBinary`) so the same schema runs on SQLite (default local
`DATABASE_URL`) and PostgreSQL (Docker Compose, production). Alembic migrations are generated against the models and
applied on container start; in `APP_ENV=development` the app also calls `create_all` for convenience. Embeddings are stored
as float32 bytes and searched in memory, avoiding a hard dependency on the `pgvector` extension.

## Consequences
* A developer can run backend + tests with no services installed (this repository's tests run on SQLite).
* JSON columns are not indexed for querying; anything filtered in SQL has its own column.
* Moving to `pgvector` later changes `ai/embeddings/index.py` only.
