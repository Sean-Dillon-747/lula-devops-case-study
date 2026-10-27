"""0002 - backfill orders.status_id from orders.status, in small batches.

Why batches: one big UPDATE locks every row it touches until it commits, bloats
WAL and can stall replicas. Small committed batches keep each lock short.

Why it is safe to rerun after a crash (resumable):
    * each batch only touches rows WHERE status_id IS NULL, so redoing work is a no-op
    * each batch commits on its own, so finished batches survive a crash
    * rows inserted/updated by the app while this runs are already handled by the
      sync trigger from 0001, so we only need to sweep ids up to max(id) at start

Walks the primary key in id ranges (keyset), not `WHERE status_id IS NULL LIMIT n`,
because status_id has no index yet: the LIMIT version rescans the table every batch.

Knobs (env vars):
    BACKFILL_BATCH_SIZE         rows per batch (default 1000)
    BACKFILL_SLEEP_SECONDS      pause between batches to throttle load (default 0.05)
    MIGRATE_FAIL_AFTER_BATCHES  failure injection for the demo/CI: raise after N batches
"""
import os
import time

BATCH_SIZE = int(os.environ.get("BACKFILL_BATCH_SIZE", "1000"))
SLEEP_SECONDS = float(os.environ.get("BACKFILL_SLEEP_SECONDS", "0.05"))
FAIL_AFTER = os.environ.get("MIGRATE_FAIL_AFTER_BATCHES")


def up(conn):
    conn.execute("SET statement_timeout = '10s'")  # per batch, not for the whole backfill
    lo, hi = conn.execute("SELECT min(id), max(id) FROM orders").fetchone()
    if lo is None:
        print("[0002] orders is empty, nothing to backfill")
        return

    batches = updated_total = 0
    start = lo
    while start <= hi:
        end = start + BATCH_SIZE
        cur = conn.execute(
            """
            UPDATE orders o
               SET status_id = s.id
              FROM order_statuses s
             WHERE o.id >= %s AND o.id < %s
               AND o.status_id IS NULL
               AND s.code = o.status
            """,
            (start, end),
        )  # autocommit: this batch is durable as soon as it returns
        batches += 1
        updated_total += cur.rowcount
        print(f"[0002] batch {batches}: ids [{start}, {end}) updated {cur.rowcount}", flush=True)

        if FAIL_AFTER and batches >= int(FAIL_AFTER):
            raise RuntimeError(f"injected failure after {batches} batches (MIGRATE_FAIL_AFTER_BATCHES)")

        start = end
        time.sleep(SLEEP_SECONDS)

    remaining = conn.execute("SELECT count(*) FROM orders WHERE status_id IS NULL").fetchone()[0]
    print(f"[0002] done: {updated_total} rows updated in {batches} batches, {remaining} still NULL")
    if remaining:
        # Not fatal here: these are rows whose status text has no lookup entry.
        # 0003 refuses to enforce NOT NULL until they are dealt with.
        rows = conn.execute(
            "SELECT status, count(*) FROM orders WHERE status_id IS NULL GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
        print(f"[0002] WARNING unmapped statuses: {rows}")


def down(conn):
    # Nothing to undo: the data lives in status_id, which 0001's down path drops.
    # Nulling it out here would only cost a full-table write for no benefit.
    print("[0002] down is a no-op (0001 down drops the column)")
