import os
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ.get("DB_URL", "postgresql://app:app@localhost:5432/app")


@pytest.fixture(autouse=True)
def baseline():
    """Every test starts from the provided baseline schema (schema.sql), un-migrated."""
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.execute((ROOT / "schema.sql").read_text())
