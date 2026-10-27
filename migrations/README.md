# Migrations — the centrepiece

This is what we care about most. Put your schema migration here — any tool (Alembic, Flyway,
sqitch, golang-migrate) or plain SQL is fine.

**The task:** evolve the baseline `orders` table (see `../schema.sql`) with a change that is
**safe under live traffic**. For example: move `status` into its own lookup/table, or add a
`currency` column with a backfill. Demonstrate:

- **Expand/contract** — the change is backwards-compatible: the old and new versions of the app
  both work *during* the rollout, so you never need a big-bang cutover.
- **Reversible** — there's a down path.
- **Mid-run failure** — if the migration half-applies in production, how do you **detect what
  actually ran** (history/version table, schema inspection) and **recover forward**? "Restore
  from a backup" is not the answer we're after.

Your CI pipeline (`.github/workflows/ci.yml`) should run this migration against the ephemeral
Postgres. Explain the safety reasoning in the top-level README, and be ready to defend it live.
