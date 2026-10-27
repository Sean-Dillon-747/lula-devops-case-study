"""Minimal, explicit migration runner.

Why hand-rolled instead of Alembic/Flyway: the case study is about detecting and
recovering from a half-applied migration, so the bookkeeping is kept visible here.

Usage:
    python migrations/migrate.py status
    python migrations/migrate.py up            # apply all pending
    python migrations/migrate.py up --to 0002  # apply up to and including 0002
    python migrations/migrate.py down          # revert the latest applied migration

Migration files (in this folder):
    NNNN_name.up.sql / NNNN_name.down.sql
        Run inside ONE transaction by default: all-or-nothing.
        Put `-- migrate:no-transaction` on the first line for statements that cannot
        run in a transaction (CREATE INDEX CONCURRENTLY). Those are split on `;` at
        line end and run one by one, so they CAN half-apply; verify.py catches that.
    NNNN_name.py
        Defines up(conn) and optionally down(conn). conn is in autocommit mode and the
        migration manages its own transactions (used for batched, resumable backfills).

Safety properties:
    * pg_try_advisory_lock: two runners can never migrate at the same time.
    * A 'running' row is committed BEFORE the migration starts, and flipped to
      'applied' in the SAME transaction as the migration (for transactional ones).
      So after a crash, the history table tells you exactly which step was in flight.
    * Checksums: an already-applied file that has been edited is refused (drift).
    * lock_timeout + retry: DDL fails fast instead of queueing behind live traffic,
      then retries with backoff.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import errors

DB_URL = os.environ.get("DB_URL", "postgresql://app:app@localhost:5432/app")
MIGRATIONS_DIR = Path(__file__).resolve().parent
ADVISORY_LOCK_ID = 727_001  # arbitrary, constant app-wide
LOCK_RETRIES = 5
NO_TX_MARKER = "-- migrate:no-transaction"

HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    checksum     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('running', 'applied', 'failed')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    error        TEXT
);
"""


class MigrationFailed(Exception):
    """Raised after a failure has been logged and recorded in schema_migrations."""


@dataclass
class Migration:
    version: str
    name: str
    kind: str  # "sql" or "py"
    up_path: Path
    down_path: Path | None

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.up_path.read_bytes()).hexdigest()[:16]


def log(msg: str) -> None:
    print(f"[migrate] {msg}", flush=True)


def discover() -> list[Migration]:
    found: dict[str, Migration] = {}
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        m = re.fullmatch(r"(\d{4})_(\w+?)(\.up\.sql|\.py)", path.name)
        if not m:
            continue
        version, name, ext = m.groups()
        if version in found:
            sys.exit(f"duplicate migration version {version}")
        if ext == ".up.sql":
            down = path.with_name(f"{version}_{name}.down.sql")
            found[version] = Migration(version, name, "sql", path, down if down.exists() else None)
        else:
            found[version] = Migration(version, name, "py", path, path)
    return [found[v] for v in sorted(found)]


def history(conn) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT version, name, checksum, status, started_at, finished_at, error "
        "FROM schema_migrations ORDER BY version"
    ).fetchall()
    keys = ("version", "name", "checksum", "status", "started_at", "finished_at", "error")
    return {r[0]: dict(zip(keys, r)) for r in rows}


def split_statements(sql: str) -> list[str]:
    # Only used for no-transaction files, which must stay simple (no DO blocks/functions).
    parts = re.split(r";\s*$", sql, flags=re.MULTILINE)
    out = []
    for p in parts:
        body = "\n".join(l for l in p.splitlines() if not l.strip().startswith("--")).strip()
        if body:
            out.append(body)
    return out


def load_py(mig: Migration):
    spec = importlib.util.spec_from_file_location(f"migration_{mig.version}", mig.up_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def with_lock_retry(fn, what: str):
    for attempt in range(1, LOCK_RETRIES + 1):
        try:
            return fn()
        except errors.LockNotAvailable:
            if attempt == LOCK_RETRIES:
                raise
            wait = 2 ** attempt
            log(f"{what}: lock_timeout hit (live traffic holds the lock), retry {attempt}/{LOCK_RETRIES - 1} in {wait}s")
            time.sleep(wait)


def mark(conn, version: str, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE schema_migrations SET status = %s, error = %s, "
        "finished_at = CASE WHEN %s = 'applied' THEN now() ELSE finished_at END "
        "WHERE version = %s",
        (status, error, status, version),
    )


def apply(conn, mig: Migration) -> None:
    # 1. Record intent in its own committed statement (conn is autocommit).
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum, status) "
        "VALUES (%s, %s, %s, 'running') "
        "ON CONFLICT (version) DO UPDATE SET status = 'running', checksum = EXCLUDED.checksum, "
        "started_at = now(), finished_at = NULL, error = NULL",
        (mig.version, mig.name, mig.checksum),
    )
    log(f"applying {mig.version}_{mig.name} ({mig.kind})")
    try:
        if mig.kind == "py":
            load_py(mig).up(conn)
            mark(conn, mig.version, "applied")
            return

        sql = mig.up_path.read_text(encoding="utf-8")
        if sql.lstrip().startswith(NO_TX_MARKER):
            # Not atomic: each statement commits on its own. Must be idempotent.
            for stmt in split_statements(sql):
                with_lock_retry(lambda s=stmt: conn.execute(s), mig.version)
            mark(conn, mig.version, "applied")
        else:
            def run_tx():
                with conn.transaction():
                    conn.execute(sql)
                    mark(conn, mig.version, "applied")  # atomic with the DDL
            with_lock_retry(run_tx, mig.version)
    except Exception as exc:
        mark(conn, mig.version, "failed", f"{type(exc).__name__}: {exc}"[:2000])
        log(f"FAILED {mig.version}: {exc}")
        log("history row marked 'failed'. Run `verify.py` to see what actually landed, "
            "fix the cause, then rerun `up` (every step is idempotent).")
        raise MigrationFailed from exc


def revert(conn, mig: Migration) -> None:
    if mig.down_path is None:
        sys.exit(f"{mig.version} has no down path")
    log(f"reverting {mig.version}_{mig.name}")
    if mig.kind == "py":
        module = load_py(mig)
        if not hasattr(module, "down"):
            sys.exit(f"{mig.version} has no down(conn)")
        module.down(conn)
        conn.execute("DELETE FROM schema_migrations WHERE version = %s", (mig.version,))
        return

    sql = mig.down_path.read_text(encoding="utf-8")

    def run_tx():
        with conn.transaction():
            conn.execute(sql)
            conn.execute("DELETE FROM schema_migrations WHERE version = %s", (mig.version,))
    with_lock_retry(run_tx, mig.version)


def cmd_status(conn, migrations: list[Migration]) -> int:
    hist = history(conn)
    problems = 0
    for mig in migrations:
        row = hist.get(mig.version)
        state = row["status"] if row else "pending"
        note = ""
        if row and row["checksum"] != mig.checksum:
            note = "  <-- CHECKSUM DRIFT: file changed after it ran"
            problems += 1
        if state in ("running", "failed"):
            note += f"  <-- INCOMPLETE: {row['error'] or 'process died mid-run'}"
            problems += 1
        print(f"  {mig.version}  {state:<8}  {mig.name}{note}")
    for version in hist.keys() - {m.version for m in migrations}:
        print(f"  {version}  in DB but no file on disk  <-- check deployed code version")
        problems += 1
    return 1 if problems else 0


def cmd_up(conn, migrations: list[Migration], to: str | None) -> None:
    hist = history(conn)
    for mig in migrations:
        if to and mig.version > to:
            break
        row = hist.get(mig.version)
        if row and row["status"] == "applied":
            if row["checksum"] != mig.checksum:
                sys.exit(f"{mig.version} was applied with a different checksum; refusing (drift)")
            continue
        if row:
            # 'running' with the advisory lock held by us means the previous runner died.
            log(f"{mig.version} found in state '{row['status']}', resuming (idempotent rerun)")
        apply(conn, mig)
    log("up to date")


def cmd_down(conn, migrations: list[Migration]) -> None:
    hist = history(conn)
    applied = [m for m in migrations if m.version in hist]
    if not applied:
        log("nothing to revert")
        return
    revert(conn, applied[-1])
    log("reverted")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["status", "up", "down"])
    parser.add_argument("--to", help="for `up`: stop after this version, e.g. 0002")
    args = parser.parse_args()

    migrations = discover()
    with psycopg.connect(DB_URL, autocommit=True) as conn:
        conn.execute("SET lock_timeout = '5s'")
        conn.execute(HISTORY_DDL)

        got_lock = conn.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,)).fetchone()[0]
        if args.command == "status":
            if not got_lock:
                log("NOTE: a migration is running right now; 'running' rows may be in flight, not crashed")
            try:
                return cmd_status(conn, migrations)
            finally:
                if got_lock:
                    conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
        if not got_lock:
            log("another migration run holds the advisory lock; refusing to run concurrently")
            return 2
        try:
            if args.command == "up":
                cmd_up(conn, migrations, args.to)
            else:
                cmd_down(conn, migrations)
        except MigrationFailed:
            return 1  # already logged and recorded in schema_migrations
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
    return 0


if __name__ == "__main__":
    sys.exit(main())