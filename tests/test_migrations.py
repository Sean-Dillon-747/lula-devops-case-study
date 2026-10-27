"""Migration safety tests. Run against a real Postgres (the CI service container).

These prove the claims in the README instead of just stating them:
  * the CURRENT app keeps working at every stage of the expand rollout
  * a backfill that dies halfway is detected (verify.py) and recovers forward
  * unknown status codes block the NOT NULL step with a clear error, and recover
  * two runners can't migrate at once
  * the whole thing is reversible

Each test resets the database to the provided baseline (schema.sql).
"""
import os
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB_URL = os.environ.get("DB_URL", "postgresql://app:app@localhost:5432/app")
MIGRATE = [sys.executable, str(ROOT / "migrations" / "migrate.py")]
VERIFY = [sys.executable, str(ROOT / "migrations" / "verify.py")]


def run(cmd, **env):
    result = subprocess.run(
        cmd, capture_output=True, text=True, env={**os.environ, "DB_URL": DB_URL, **env}
    )
    print(result.stdout, result.stderr)
    return result


def sql(query, *params):
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        cur = conn.execute(query, params or None)
        return cur.fetchall() if cur.description else None


@pytest.fixture
def old_app():
    """The app exactly as it is today: only knows about the `status` text column."""
    sys.path.insert(0, str(ROOT / "app"))
    from fastapi.testclient import TestClient
    import main
    return TestClient(main.app)


def bulk_seed(rows):
    sql("""INSERT INTO orders (amount, status)
           SELECT 1, (ARRAY['pending','paid','shipped'])[1 + (g %% 3)]
           FROM generate_series(1, %s) g""", rows)


@pytest.mark.parametrize("stage", [None, "0001", "0002", "0003"])
def test_current_app_works_at_every_rollout_stage(stage, old_app):
    if stage:
        assert run(MIGRATE + ["up", "--to", stage], BACKFILL_SLEEP_SECONDS="0").returncode == 0

    created = old_app.post("/orders", json={"amount": 12.5, "status": "paid"})
    assert created.status_code == 200
    assert old_app.get("/orders").status_code == 200

    if stage:  # the sync trigger fills status_id for writes from the old app
        assert sql("SELECT status_id FROM orders WHERE id = %s", created.json()["id"]) == [(2,)]


def test_backfill_crash_is_detected_and_recovers_forward():
    bulk_seed(2000)
    assert run(MIGRATE + ["up", "--to", "0001"]).returncode == 0

    crashed = run(MIGRATE + ["up"], BACKFILL_BATCH_SIZE="100", BACKFILL_SLEEP_SECONDS="0",
                  MIGRATE_FAIL_AFTER_BATCHES="3")
    assert crashed.returncode == 1
    assert sql("SELECT status FROM schema_migrations WHERE version = '0002'") == [("failed",)]

    # Detect what actually landed: some rows filled, some not.
    filled, missing = sql("SELECT count(status_id), count(*) - count(status_id) FROM orders")[0]
    assert filled > 0 and missing > 0
    report = run(VERIFY)
    assert report.returncode == 1 and "PARTIAL" in report.stdout

    # Recover forward: just rerun.
    assert run(MIGRATE + ["up"], BACKFILL_BATCH_SIZE="100", BACKFILL_SLEEP_SECONDS="0").returncode == 0
    assert run(VERIFY).returncode == 0


def test_unknown_status_blocks_not_null_then_recovers(old_app):
    assert run(MIGRATE + ["up", "--to", "0002"], BACKFILL_SLEEP_SECONDS="0").returncode == 0
    old_app.post("/orders", json={"amount": 1, "status": "refunded"})  # old app accepts any string

    blocked = run(MIGRATE + ["up"])
    assert blocked.returncode == 1
    assert "still have NULL status_id" in blocked.stdout
    assert sql("SELECT is_nullable FROM information_schema.columns "
               "WHERE table_name = 'orders' AND column_name = 'status_id'") == [("YES",)]

    sql("INSERT INTO order_statuses (id, code) VALUES (4, 'refunded')")
    assert run(MIGRATE + ["up"]).returncode == 0
    assert run(VERIFY).returncode == 0


def test_concurrent_runner_is_refused():
    with psycopg.connect(DB_URL, autocommit=True) as holder:
        holder.execute("SELECT pg_advisory_lock(727001)")
        assert run(MIGRATE + ["up"]).returncode == 2
    assert run(MIGRATE + ["up"], BACKFILL_SLEEP_SECONDS="0").returncode == 0


def test_full_rollout_is_reversible():
    assert run(MIGRATE + ["up"], BACKFILL_SLEEP_SECONDS="0").returncode == 0
    for _ in range(3):
        assert run(MIGRATE + ["down"]).returncode == 0
    assert sql("SELECT count(*) FROM information_schema.columns "
               "WHERE table_name = 'orders' AND column_name = 'status_id'") == [(0,)]
    assert run(VERIFY).returncode == 0
    assert run(MIGRATE + ["up"], BACKFILL_SLEEP_SECONDS="0").returncode == 0
    assert run(VERIFY).returncode == 0
