"""Verify the PostgreSQL path without Docker: embedded PostgreSQL (pip install pgserver) -> Alembic migration -> test suite.

    python backend/scripts/verify_postgres.py            -> prints PASS/FAIL

Checks: (1) `alembic upgrade head` builds the schema on PostgreSQL, (2) there is no drift between models and migration,
(3) the API/integration test-suite passes unchanged against PostgreSQL (NEUROFORGE_TEST_DATABASE_URL).
With a real server, skip this script and run: DATABASE_URL=postgresql+psycopg2://… alembic upgrade head && pytest.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def run(cmd: list[str], env: dict, label: str) -> int:
    p = subprocess.run(cmd, cwd=str(REPO), env=env, capture_output=True, text=True)
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-6:])
    print(f"[{'ok' if p.returncode == 0 else 'FAIL'}] {label}\n    " + tail.replace("\n", "\n    ")[:900])
    return p.returncode


def main() -> int:
    import pgserver

    pgdata = Path(tempfile.mkdtemp(prefix="neuroforge-pg-"))
    srv = pgserver.get_server(pgdata, cleanup_mode="stop")
    try:
        uri = srv.get_uri()  # postgresql://postgres:@127.0.0.1:PORT/postgres
        sa_url = uri.replace("postgresql://", "postgresql+psycopg2://", 1)
        import sqlalchemy as sa

        with sa.create_engine(sa_url, isolation_level="AUTOCOMMIT").connect() as c:
            c.execute(sa.text("CREATE DATABASE neuroforge"))
            print("server:", c.execute(sa.text("select version()")).scalar()[:60])
        url = sa_url.rsplit("/", 1)[0] + "/neuroforge"
        env = {**os.environ, "DATABASE_URL": url, "NEUROFORGE_TEST_DATABASE_URL": url, "PYTHONPATH": str(REPO / "backend")}
        rc = run([sys.executable, "-m", "alembic", "upgrade", "head"], env, "alembic upgrade head on PostgreSQL")
        rc |= run([sys.executable, "-m", "alembic", "check"], env, "alembic check (models == migration)")
        if rc == 0:
            insp = sa.inspect(sa.create_engine(url))
            tables = sorted(insp.get_table_names())
            print(f"tables ({len(tables)}):", ", ".join(tables))
            rc |= run([sys.executable, "-m", "pytest", "backend/tests/api", "backend/tests/integration", "-q", "-p", "no:cacheprovider"], env,
                      "pytest api + integration against PostgreSQL")
        print("POSTGRESQL PATH:", "PASS" if rc == 0 else "FAIL")
        return rc
    finally:
        srv.cleanup()


if __name__ == "__main__":
    sys.exit(main())
