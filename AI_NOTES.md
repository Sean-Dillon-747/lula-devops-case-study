# How I used AI

**Tool:** Claude (chat plus its own sandbox with Postgres 16, used to run code before handing it to me).

**Split of work:** Claude wrote most of the code. I set the priorities, made the design
calls, reviewed every file before committing, ran everything on my own machine (Windows
/ PowerShell / Docker Desktop), and demoed the failure scenarios by hand. Nothing went
in that I can't explain line by line.

**Rule I worked by:** don't accept a safety claim without a test or a demo that proves
it. Most of the corrections below came from that rule, not from reading code.

## Decisions I made

- **Status lookup table over a `currency` column.** A nullable column barely has a
  contract phase; moving `status` exercises real expand/contract, with a trigger,
  backfill and a column drop.
- **Hand-rolled runner instead of Alembic.** Alembic's version table records only
  success. The brief is about detecting a *half*-applied migration, so I wanted
  `running`/`failed` states and a separate schema verifier to be visible.
- **Unknown status codes:** the current API accepts any string. Options were (a) the
  trigger rejects them (changes old-app behaviour mid-rollout), (b) auto-insert into the
  lookup (junk accumulates), or (c) gate NOT NULL on zero NULLs and tighten validation in
  app v2. I chose (c).
- **No automatic retries on the Azure migration job,** even though the steps are
  idempotent: some failures need a person to look before rerunning.
- **Documented the contract phase (0004/0005) instead of building it,** to spend the time
  on proving the expand phase.

## AI output I corrected or overrode

| What happened | How it was caught | Fix |
|---|---|---|
| Claude said Ctrl+C marks a step `failed`. Wrong: `KeyboardInterrupt` isn't an `Exception`, so the row stays `running`. | Questioned it in review | Corrected. It's actually the more realistic crash demo. |
| After mapping a new status code, nothing filled the leftover NULL rows: 0002 was already `applied` and the trigger only fires on writes. | Scenario test | Catch-up pass at the start of 0003 |
| `verify.py` reported a fresh, un-migrated DB as PARTIAL. | Ran it on a clean DB | Checks only count when the column exists |
| A refactor put a new exception class under the `@dataclass` decorator, breaking the runner. | Test run | Moved it |
| psycopg treats `%` as a placeholder, so `g % 3` in a test query failed. | Test run | `%%` |
| Key Vault names could exceed Azure's 24-character limit for some service/environment combos. | Review | Tightened the module's name validation |
| `# syntax=docker/dockerfile:1` in the Dockerfile forces an extra registry pull for no benefit. | Build failed in a restricted network | Removed |
| Claude killed its own shell twice with an over-broad `pkill -f`. | Obvious | Kill by port/PID |
| Pinned `psycopg[binary]==3.2.1` has no wheel for Python 3.13 (my default). | Local install failed | Python 3.12 venv, same as the image |

## Traps I knew to avoid, and verified weren't there

These are mistakes AI tools commonly produce for this kind of task:

- `ALTER COLUMN ... SET NOT NULL` directly, which scans the whole table under an exclusive lock
- `ADD CHECK ... NOT VALID` and `VALIDATE` **in the same transaction** (the lock is held
  through the scan, defeating the purpose)
- `CREATE INDEX CONCURRENTLY` inside a transaction (an error at best, an `INVALID` index at worst)
- `WHERE status_id IS NULL LIMIT n` batching on an unindexed column (rescans every batch)
- `curl` in a `python:slim` healthcheck (not installed)
- A liveness probe that checks the database (restart storm on a DB blip)
- Prometheus labels from user input (cardinality explosion)
- The DB password as a Terraform variable, or a regular `random_password` (ends up in state)
- Returning raw driver errors from the health endpoint (leaks hostnames)

## How I verified things AI couldn't

- The AI sandbox couldn't reach the Terraform registry, so Claude checked every resource
  and attribute against the azurerm v4.81.0 and random provider **source code**. I then
  ran `terraform validate` locally (passed first time), and CI runs it on every push.
- Docker Hub was blocked in the sandbox too: the Dockerfile was linted with hadolint
  there, and I did the first real build and run locally.
