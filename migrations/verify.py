"""Inspect what ACTUALLY exists in the database and compare it with schema_migrations.

The history table says what the runner *believes* happened. After a crash, a
non-transactional step, or someone hand-running SQL in prod, that belief can be
wrong. This script checks the real schema (pg_catalog / information_schema) and
the data, step by step, and tells you what landed.

    python migrations/verify.py      exit 0 = consistent and complete, 1 = needs attention
"""
import os
import sys

import psycopg

DB_URL = os.environ.get("DB_URL", "postgresql://app:app@localhost:5432/app")


def one(conn, sql, *params):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def checks(conn):
    """version -> list of (description, passed)."""
    has_col = bool(one(conn, """SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'orders' AND column_name = 'status_id'"""))
    fk_valid = one(conn, "SELECT convalidated FROM pg_constraint WHERE conname = 'orders_status_id_fkey'")
    nulls = one(conn, "SELECT count(*) FROM orders WHERE status_id IS NULL") if has_col else None
    filled = one(conn, "SELECT count(*) FROM orders WHERE status_id IS NOT NULL") if has_col else 0
    not_null = one(conn, """SELECT is_nullable = 'NO' FROM information_schema.columns
                            WHERE table_name = 'orders' AND column_name = 'status_id'""")
    return {
        "0001": [
            ("order_statuses table exists", bool(one(conn, "SELECT to_regclass('order_statuses') IS NOT NULL"))),
            ("orders.status_id column exists", has_col),
            ("FK orders_status_id_fkey exists", fk_valid is not None),
            ("sync trigger exists", bool(one(conn, "SELECT 1 FROM pg_trigger WHERE tgname = 'orders_sync_status_id'"))),
        ],
        "0002": [
            (f"rows backfilled (found {filled})", bool(filled)),
            (f"no orders with NULL status_id (found {nulls})", nulls == 0),
        ],
        "0003": [
            ("status_id is NOT NULL", bool(not_null)),
            ("FK is validated", bool(fk_valid)),
        ],
    }


def main():
    problems = 0
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        history = dict(conn.execute("SELECT version, status FROM schema_migrations").fetchall()) \
            if one(conn, "SELECT to_regclass('schema_migrations') IS NOT NULL") else {}

        for version, results in checks(conn).items():
            recorded = history.get(version, "pending")
            passed = sum(ok for _, ok in results)
            observed = "complete" if passed == len(results) else "absent" if passed == 0 else "PARTIAL"

            consistent = (
                (recorded == "applied" and observed == "complete")
                or (recorded == "pending" and observed == "absent")
            )
            verdict = "ok" if consistent else "ATTENTION"
            if not consistent:
                problems += 1
            print(f"{version}  history={recorded:<8} schema={observed:<8} {verdict}")
            for desc, ok in results:
                print(f"        [{'x' if ok else ' '}] {desc}")

            if recorded in ("running", "failed"):
                print("        -> half-applied: fix the cause, rerun `migrate.py up` (steps are idempotent)")
            elif recorded == "applied" and observed != "complete":
                print("        -> DRIFT: history says applied but schema/data disagrees (new unmapped data, or a manual change). Investigate before migrating further.")
            elif recorded == "pending" and observed != "absent":
                print("        -> objects exist without a history row (hand-run SQL?). Rerunning `up` is safe; it is idempotent.")

        if one(conn, "SELECT 1 FROM pg_constraint WHERE conname = 'orders_status_id_not_null'"):
            problems += 1
            print("Temporary CHECK orders_status_id_not_null still present: 0003 stopped midway. "
                  "Rerun `migrate.py up`.")

        invalid = conn.execute("""
            SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
            WHERE NOT i.indisvalid""").fetchall()
        for (name,) in invalid:
            problems += 1
            print(f"INVALID index {name}: left by a failed CREATE INDEX CONCURRENTLY. "
                  f"DROP INDEX CONCURRENTLY {name}; then rerun.")

    print("\nRESULT:", "consistent" if not problems else f"{problems} item(s) need attention")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
