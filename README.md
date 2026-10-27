# Orders API: from "runs on my machine" to "safe to run in production"

DevOps / Platform Engineer case study. The original brief is in [BRIEF.md](BRIEF.md).

**Where the time went.** The schema migration got most of the effort, as the brief
asked. It is backwards-compatible, reversible, resumable after a crash, and the CI
pipeline proves those claims with tests instead of just stating them. The container,
observability and Terraform are deliberately smaller.

| Piece | Where |
|---|---|
| Migration runner, steps, verifier | [`migrations/`](migrations) |
| Tests that prove the migration is safe | [`tests/`](tests) |
| Pipeline | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) |
| Container | [`Dockerfile`](Dockerfile), [`docker-compose.yml`](docker-compose.yml) |
| Logs and metrics | [`app/observability.py`](app/observability.py) |
| The alert (and the one I didn't set) | [`observability/alerts.yml`](observability/alerts.yml) |
| Azure footprint | [`terraform/`](terraform) |
| How I used AI | [`AI_NOTES.md`](AI_NOTES.md) |

## Run it

```bash
docker compose up --build        # db -> migrate job (must succeed) -> app on :8000
curl localhost:8000/readyz
curl localhost:8000/metrics
```

Tests need a running Postgres. They **reset the database** to `schema.sql` before each test.

```bash
docker compose up -d db
pip install -r requirements-dev.txt
pytest -v tests
```

Migration commands (`DB_URL` defaults to the local compose DB):

```bash
python migrations/migrate.py status         # what the history table believes
python migrations/migrate.py up [--to 0002] # apply pending steps
python migrations/migrate.py down           # revert the latest step
python migrations/verify.py                 # what the database ACTUALLY contains
```

---

## 1. The migration (the centrepiece)

### The change

Move `orders.status` (free text) into an `order_statuses` lookup table, referenced by
`orders.status_id`. This is the textbook expand/contract case: the old column cannot
just be dropped while running code still reads and writes it.

### Rollout: every step leaves old and new code working

| Step | What happens | Who is running | Lock impact |
|---|---|---|---|
| **0001 expand** | Create the `order_statuses` table. Add a **nullable** `status_id` column (metadata-only change). Add the FK as `NOT VALID` (existing rows not scanned). Add a **sync trigger** that fills `status_id` from `status` on every insert/update. | Current app, unchanged | A brief lock only; `lock_timeout` 5s plus retry |
| **0002 backfill** | Fill `status_id` in batches of 1,000 rows, each batch committed separately. Walks primary-key ranges, because `WHERE status_id IS NULL LIMIT n` would rescan an unindexed column every batch. Throttled. | Current app | Row locks for one batch at a time |
| *deploy app v2* | Reads `status_id`, writes **both** columns, and only accepts known statuses. | v1 and v2 side by side | none |
| **0003 enforce** | `ADD CHECK (status_id IS NOT NULL) NOT VALID`, then `VALIDATE` (a scan that does **not** block reads or writes), then `SET NOT NULL` (no scan, because Postgres 12+ trusts the validated check), then drop the check. Also validates the FK. | v1 and v2 | Brief locks only |
| *deploy app v3* | Writes `status_id` only. | v2 and v3 | none |
| **0004 contract** *(designed, not built)* | Drop the sync trigger. **It must go before v3 is the only writer:** it derives `status_id` from `status` on every insert, so rows from v3 (which no longer sends `status`) would silently become `pending`. | v3 only | Brief lock |
| **0005 contract** *(designed, not built)* | Drop `orders.status`. | v3 only | Brief lock |

Two details that are easy to get wrong:

- **0003 runs each statement in its own transaction on purpose.** In one transaction,
  the exclusive lock from `ADD CONSTRAINT` would be held until commit, so `VALIDATE`'s
  full-table scan would run under it. That would block all traffic, which is the very
  thing the pattern exists to avoid.
- **The current API accepts any status string.** A row like `status='refunded'` gets a
  NULL `status_id`. 0003 refuses to continue with a clear message rather than failing
  half-way through validation. The fix is to map the code in `order_statuses` (or fix
  the data) and rerun; 0003 starts with a catch-up pass for codes mapped after 0002 ran.

### Reversible

Every step has a down path: `migrate.py down` reverts the latest applied step. After
0001–0003 the down path is lossless. After the contract steps, "down" means recreating
`status` and backfilling it from `status_id`. That is possible, but it is a
roll-*forward* in disguise, and I would say so honestly in a change review.

### The mid-run failure playbook

The runner (`migrations/migrate.py`) is hand-rolled rather than Alembic, so that the
bookkeeping is visible:

- A `schema_migrations` row is written as **`running` before** a step starts. It flips to
  `applied` **in the same transaction** as the change (for transactional steps), or is
  marked `failed` with the error.
- A **Postgres advisory lock** means two runners can never migrate at the same time.
- **Checksums** refuse to continue if an applied file was edited afterwards (drift).
- **`lock_timeout` plus retry with backoff** means DDL fails fast instead of queueing
  behind live traffic. Production would use 1–2s; while DDL waits for its lock, *new*
  queries queue behind it.
- **Every step is idempotent** (`IF NOT EXISTS`, catalogue-guarded constraints,
  `WHERE status_id IS NULL`), so recovery is always "fix the cause, rerun".

**Detect what actually ran.** Two independent sources, compared:

```text
$ python migrations/migrate.py status        # what the runner believed
  0001  applied   expand_status_lookup
  0002  failed    backfill_status_id  <-- INCOMPLETE: RuntimeError: injected failure after 2 batches

$ python migrations/verify.py                # what the schema and data actually show
0002  history=failed   schema=PARTIAL  ATTENTION
        [x] rows backfilled (found 10)
        [ ] no orders with NULL status_id (found 10)
        -> half-applied: fix the cause, rerun `migrate.py up` (steps are idempotent)
```

`verify.py` checks the real catalogue (`information_schema`, `pg_constraint`,
`pg_trigger`, `pg_index`). It also catches what the history table can't: objects
created by hand-run SQL, an applied step whose effects were later undone, an `INVALID`
index left behind by a failed `CREATE INDEX CONCURRENTLY`, and a temporary check left by
an interrupted 0003.

**Recover forward.**

| Situation | What you see | Do |
|---|---|---|
| Process died (OOM, pod evicted, Ctrl+C) | `running` row, PARTIAL schema | Rerun `up`. It resumes; only NULL rows are touched. |
| Runner died but its SQL is still running on the server | Rerun is refused: lock held | Check `pg_stat_activity`. Wait for the query, or `pg_terminate_backend` it, then rerun. (This showed up in testing: the advisory lock correctly outlived the killed client.) |
| A step errored (bad data, lock timeout) | `failed` row with the error | Read `verify.py`, fix the cause, rerun. |
| Two people run migrations at once | Second exits with code 2 | Nothing. That's the lock working. |
| Someone edited an applied file | `CHECKSUM DRIFT`, `up` refuses | Revert the edit. Changes go in a **new** migration. |

Restoring a backup is deliberately not in the table. Point-in-time restore exists (see
Terraform) as a disaster-recovery tool, not as a migration tool.

---

## 2. CI/CD: the pipeline is the "deploy"

`.github/workflows/ci.yml`, on every push:

1. **Build** the image (tagged with the commit SHA).
2. **Migration safety tests** against the Postgres service container. Each test starts
   from the baseline and proves one claim:
   - the **current, unmodified app** works at every rollout stage (the real `main.py`
     through FastAPI's TestClient)
   - a backfill killed after 3 batches → `failed` / `PARTIAL` → rerun → consistent
   - unknown statuses block NOT NULL → map the code → recovers
   - a second runner is refused
   - full `down` ×3 then `up` again is clean
3. **Deploy:** reset to the baseline plus 50k rows, start the **built image**, run
   `migrate.py up` **while 200 writes hit the app**. The job fails if a single write fails.
4. **Verify** (`status` + `verify.py`, both exit non-zero on problems) and a **smoke test**.
5. Separate jobs: `promtool check rules` on the alert, and `terraform fmt` + `validate`.

Locally, 50,031 rows were backfilled in 51 batches with all 200 concurrent writes
succeeding.

## 3. Container

- **Multi-stage:** dependencies install into a venv in a builder stage; only the venv and
  code ship.
- **Non-root**, fixed UID 10001; the code is owned by root, so the app can't modify itself.
- **One image, two jobs:** the same image runs the app and `migrate.py`, so schema and
  code are versioned together. In compose, a one-shot `migrate` service must succeed
  before `app` starts. That's the local version of the Azure migration job.
- **Healthcheck** uses the Python stdlib (slim images have no curl). Exec-form `CMD` means
  uvicorn gets SIGTERM directly and shuts down gracefully.
- **Runtime hardening** in compose: read-only filesystem, all Linux capabilities
  dropped, `no-new-privileges`. `.dockerignore` keeps `.git`, `.env` and tests out of
  the image.
- **Probes split:** `/livez` never touches the DB, so a DB blip can't restart every
  replica at once. `/readyz` does, so an unhealthy replica leaves the load balancer
  without restarting. Error details are logged, not returned to callers.
- Production would pin the base image by digest and let Dependabot/Renovate bump it.

## 4. Observability

- **Structured logs:** one JSON line per event on stdout, each carrying a `request_id`
  (taken from `X-Request-ID` or generated, and returned in the response) so one request
  can be followed end to end. Probes log at DEBUG so they don't drown real traffic.
- **Metrics** on `/metrics`: RED metrics (Rate, Errors, Duration) per route, and
  `orders_created_total`. Labels are **bounded on purpose**: route *templates*, never raw
  paths, and status codes outside the known set become `other`. The current API accepts
  any string, so labelling by raw input would let a user create unlimited time series.
- **The alert I set:** an error-budget **burn rate** on `/orders` (99.5% SLO; page when
  the 1h *and* 5m windows both exceed 14.4× budget). It measures what customers feel, and
  it is exactly what a bad deploy or a write-breaking migration looks like.
- **The alert I didn't set:** "CPU > 80%" or "container restarted". Those are causes, not
  symptoms. They page people at 3am for things the platform already heals, which trains
  people to ignore pages. If saturation ever hurts users, the burn-rate alert fires anyway.
- **Not built (bonus):** tracing. Next step: OpenTelemetry's FastAPI and psycopg
  instrumentation exporting to Azure Monitor / Application Insights, with `trace_id`
  added to every log line.

## 5. Terraform and the Azure mapping

`terraform/` validates against azurerm 4.x (CI runs `fmt -check` and `validate`).

- **Boundaries:** the root module is the pod's shared platform (resource group, Log
  Analytics, Container Apps environment). `modules/orders_service` is everything one
  service needs (identity, Key Vault, Postgres, app, migration job), so the next R&D idea
  is one more module call with the same defaults.
- **Secrets never enter state.** The DB password comes from an **ephemeral**
  `random_password` and is passed only to **write-only** arguments
  (`administrator_password_wo`, Key Vault `value_wo`). Terraform sends it to Azure but
  doesn't record it in the plan or state. Rotation: bump `db_password_version` and apply.
- **No secrets in app config.** A user-assigned managed identity gets *Key Vault Secrets
  User* (read-only) and *AcrPull*. Container Apps resolves the Key Vault reference at
  runtime. The deployer gets *Secrets Officer*; nobody gets admin.
- **State:** remote `azurerm` backend, one blob per environment
  (`envs/dev.backend.hcl`), Entra ID auth, blob locking, versioning. The pipeline
  authenticates with OIDC federation, so there is no client secret anywhere. State still
  holds sensitive metadata, so access is restricted, and `*.tfstate` is git-ignored.
- **Migration job:** an `azurerm_container_app_job` runs `migrate.py up` from the **same
  image**, 1 replica, **no automatic retries** (steps are idempotent, but a failure like
  unknown status codes needs a person to read `verify.py`). The release pipeline starts
  it and waits for success before shifting traffic to the new revision.
- **Guard rails:** `prevent_destroy` on the server and database; `ignore_changes = [zone]`
  so an HA failover isn't reported as drift.
- **Labelled shortcuts:** public network access on Key Vault and Postgres, an "allow Azure
  services" firewall rule, and a shared admin login for app and migrations. Production:
  VNet integration plus private endpoints; a schema-owner role for migrations and a
  DML-only role for the app; then Entra authentication for the app's identity with
  password auth turned off.

**Mapping to the Lula stack**

| Here | Azure |
|---|---|
| GitHub Actions | Azure DevOps Pipelines (same stages; OIDC service connection) |
| `docker build` in CI | Build and push to ACR, tagged and pinned by digest |
| Postgres service container | Azure Database for PostgreSQL Flexible Server (Terraform). The same migrations work on Azure SQL with T-SQL equivalents: online index operations, `WITH NOCHECK` then `CHECK` for constraints. |
| `migrate` compose service / CI step | Container Apps Job (Terraform) or a Kubernetes Job / Helm pre-upgrade hook on AKS |
| `app` compose service | Azure Container Apps (Terraform), or a Deployment on AKS |
| `DB_URL` env var | Key Vault secret via managed identity |
| stdout JSON logs, `/metrics` | Log Analytics, Azure Monitor managed Prometheus, alert rule as-is |

## What I'd do next

1. Build app v2/v3 and the contract migrations (0004, 0005), with a test that runs v1
   and v2 side by side against the same DB.
2. `CREATE INDEX CONCURRENTLY` on `orders.status_id` as a non-transactional step. The
   runner supports it, and `verify.py` already detects the `INVALID` index a failed run
   leaves behind.
3. A real release pipeline: push to ACR, `terraform plan` on PR / `apply` on merge with
   approval for prod, start the migration job, shift traffic only if it succeeds.
4. Tracing (above), and a slow-burn alert to go with the fast-burn one.
5. Private networking and Entra-only database authentication.
6. `GET /orders` returns every row; it needs pagination before the table grows.
