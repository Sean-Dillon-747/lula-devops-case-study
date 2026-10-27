"""0003 - make status_id NOT NULL and validate the FK, without a long blocking lock.

The naive version, `ALTER TABLE orders ALTER COLUMN status_id SET NOT NULL`, scans the
whole table while holding an ACCESS EXCLUSIVE lock: every read and write on orders
waits for the scan.

Instead:
    1. ADD CHECK (status_id IS NOT NULL) NOT VALID   brief exclusive lock, no scan
    2. VALIDATE CONSTRAINT (check and FK)            scans, but under SHARE UPDATE
                                                     EXCLUSIVE: reads AND writes continue
    3. SET NOT NULL                                  brief lock, no scan (PG12+ uses the
                                                     validated CHECK as proof)
    4. DROP the now-redundant CHECK

Each step is its own autocommitted statement ON PURPOSE. If they ran in one
transaction, step 1's exclusive lock would be held until commit, so step 2's scan
would run under it, which defeats the whole point.

Every step is idempotent, so after a mid-run failure you just rerun.

Rollout precondition: the app version that only accepts known statuses
(pending/paid/shipped) must be live first, because from step 1 onwards new rows
with an unknown status are rejected.
"""

CHECK_NAME = "orders_status_id_not_null"


def _constraint_exists(conn, name):
    return conn.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (name,)).fetchone() is not None


def up(conn):
    # Catch-up sweep: picks up rows whose status code was mapped in order_statuses
    # AFTER 0002 ran (0002 is already 'applied', and the trigger only fires on writes).
    # Normally touches zero rows.
    cur = conn.execute("""
        UPDATE orders o SET status_id = s.id
          FROM order_statuses s
         WHERE o.status_id IS NULL AND s.code = o.status""")
    if cur.rowcount:
        print(f"[0003] catch-up filled {cur.rowcount} rows")

    # Gate: refuse early with a clear message instead of a cryptic VALIDATE error.
    nulls = conn.execute("SELECT count(*) FROM orders WHERE status_id IS NULL").fetchone()[0]
    if nulls:
        raise RuntimeError(
            f"{nulls} orders still have NULL status_id (backfill incomplete or unknown "
            "status codes). Rerun 0002 or map the codes in order_statuses, then rerun."
        )

    if not _constraint_exists(conn, CHECK_NAME):
        print("[0003] add CHECK NOT VALID")
        conn.execute(f"ALTER TABLE orders ADD CONSTRAINT {CHECK_NAME} CHECK (status_id IS NOT NULL) NOT VALID")

    print("[0003] validate CHECK (online scan)")
    conn.execute(f"ALTER TABLE orders VALIDATE CONSTRAINT {CHECK_NAME}")

    print("[0003] validate FK (online scan)")
    conn.execute("ALTER TABLE orders VALIDATE CONSTRAINT orders_status_id_fkey")

    print("[0003] SET NOT NULL (no scan, uses validated CHECK)")
    conn.execute("ALTER TABLE orders ALTER COLUMN status_id SET NOT NULL")

    print("[0003] drop redundant CHECK")
    conn.execute(f"ALTER TABLE orders DROP CONSTRAINT IF EXISTS {CHECK_NAME}")


def down(conn):
    conn.execute(f"ALTER TABLE orders DROP CONSTRAINT IF EXISTS {CHECK_NAME}")
    conn.execute("ALTER TABLE orders ALTER COLUMN status_id DROP NOT NULL")
    # The FK stays validated: harmless, and 0001 down removes it entirely.
