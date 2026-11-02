import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings


@pytest.fixture(scope="session")
def test_dsn():
    base = os.getenv("TEST_DATABASE_URL")
    if not base:
        pytest.fail("TEST_DATABASE_URL is required: tests create a separate temporary PostgreSQL database.")
    name = "cc_rag_test_" + uuid4().hex[:12]
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    yield make_conninfo(base, dbname=name)
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def settings(test_dsn, tmp_path):
    return Settings(database_url=test_dsn, origin="http://testserver", documents_dir=tmp_path,
                    frontend_dir=Path(os.getenv("FRONTEND_DIR", str(Path(__file__).resolve().parents[2] / "frontend"))),
                    embedding_url="https://embedding.test/v1", embedding_key="test-only", embedding_model="test-" + uuid4().hex,
                    llm_url="https://llm.test/v1", llm_key="test-only", llm_model="test-model")
