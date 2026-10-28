<#
.SYNOPSIS
  Recording demo for the case study. Runs each section on cue, echoing every command
  so viewers see exactly what runs. Press any key to advance (the key isn't shown).

.EXAMPLE
  .\scripts\demo.ps1 -Section 0      # off-camera prep: clean DB + 200k rows (run first!)
  .\scripts\demo.ps1 -Section 2,3,4  # just the migration part
  .\scripts\demo.ps1                 # sections 1-7 in order

  Run from the repo root, with the venv active.
#>
param([int[]]$Section = 1..7)

$ErrorActionPreference = "Continue"  # a non-zero exit must never kill the demo mid-recording
$env:DB_URL = "postgresql://app:app@localhost:5432/app"

function Title($text) { Write-Host "`n=== $text ===" -ForegroundColor Yellow }
function Note($text) { Write-Host "# $text" -ForegroundColor DarkGray }
function Wait-Key {
    if ([Console]::IsInputRedirected) { return }
    [void][Console]::ReadKey($true)
}
function Run([string]$cmd) {
    Write-Host "PS> $cmd" -ForegroundColor Cyan
    Invoke-Expression $cmd
}
function Sql([string]$query) {
    Write-Host "SQL> $query" -ForegroundColor Cyan
    docker compose exec -T db psql -U app -d app -c $query
}
function Clear-DemoEnv {
    "BACKFILL_BATCH_SIZE", "BACKFILL_SLEEP_SECONDS", "MIGRATE_FAIL_AFTER_BATCHES" |
        ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
}

# --- 0. Prep (OFF camera) ----------------------------------------------------------
if ($Section -contains 0) {
    Title "Prep: clean baseline + 200k orders (off camera)"
    Clear-DemoEnv
    docker compose down -v
    docker compose up -d --wait db
    # The image restarts Postgres after running schema.sql, so wait until the seeded table answers.
    do { Start-Sleep 2 } until ((docker compose exec -T db psql -U app -d app -tAc "SELECT count(*) FROM orders" 2>$null) -match "^\s*\d+")
    Start-Sleep 3
    docker compose exec -T db psql -U app -d app -q -c "INSERT INTO orders (amount, status) SELECT (random()*1000)::numeric(12,2), (ARRAY['pending','paid','shipped'])[1 + floor(random()*3)::int] FROM generate_series(1, 200000);"
    docker compose exec -T db psql -U app -d app -c "SELECT count(*) AS orders FROM orders;"
    Write-Host "Ready. Start recording, then run: .\scripts\demo.ps1" -ForegroundColor Green
}

# --- 1. Intro -------------------------------------------------------------------
if ($Section -contains 1) {
    Title "1. Baseline: 200k orders, status is free text"
    Run "python migrations/migrate.py status"
    Sql "\d orders"
    Wait-Key
}

# --- 2. Expand ------------------------------------------------------------------
if ($Section -contains 2) {
    Title "2. Expand (0001): lookup table, nullable FK, sync trigger"
    Run "python migrations/migrate.py up --to 0001"
    Sql "\d orders"
    Wait-Key
    Note "The CURRENT app only writes the status text. The trigger keeps it compatible:"
    Sql "INSERT INTO orders (amount, status) VALUES (42, 'paid') RETURNING id, status, status_id;"
    Wait-Key
}

# --- 3. Crash mid-backfill, detect, recover forward ------------------------------
if ($Section -contains 3) {
    Title "3. Backfill crashes halfway (failure injected after 60 batches)"
    $env:BACKFILL_BATCH_SIZE = "1000"
    $env:BACKFILL_SLEEP_SECONDS = "0"
    $env:MIGRATE_FAIL_AFTER_BATCHES = "60"
    Write-Host "PS> python migrations/migrate.py up --to 0002   (MIGRATE_FAIL_AFTER_BATCHES=60)" -ForegroundColor Cyan
    python migrations/migrate.py up --to 0002 | Select-Object -Last 4
    Remove-Item Env:MIGRATE_FAIL_AFTER_BATCHES
    Wait-Key

    Title "Detect: what the runner believed vs what actually landed"
    Run "python migrations/migrate.py status"
    Wait-Key
    Run "python migrations/verify.py"
    Wait-Key

    Title "Recover forward (throttled) - meanwhile, try to break it"
    $env:BACKFILL_SLEEP_SECONDS = "0.1"
    $repo = (Get-Location).Path
    $py = (Get-Command python).Source
    $job = Start-Job -ScriptBlock {
        param($repo, $py, $url)
        Set-Location $repo
        $env:DB_URL = $url; $env:BACKFILL_BATCH_SIZE = "1000"; $env:BACKFILL_SLEEP_SECONDS = "0.1"
        & $py migrations/migrate.py up --to 0002 2>&1
    } -ArgumentList $repo, $py, $env:DB_URL
    Note "Resume is running in the background..."
    Start-Sleep 3
    Note "A second runner at the same time is refused (advisory lock):"
    Run "python migrations/migrate.py up; `"exit code: `$LASTEXITCODE`""
    Note "Live traffic keeps writing during the backfill:"
    Sql "INSERT INTO orders (amount, status) VALUES (7, 'shipped') RETURNING id, status_id;"
    Note "Waiting for the resume to finish..."
    $job | Wait-Job | Receive-Job | Select-Object -Last 3
    Remove-Job $job
    Run "python migrations/verify.py"
    Clear-DemoEnv
    Wait-Key
}

# --- 4. Gate, enforce, reverse ----------------------------------------------------
if ($Section -contains 4) {
    Title "4. The current API accepts ANY status string..."
    Sql "INSERT INTO orders (amount, status) VALUES (1, 'refunded') RETURNING id, status_id;"
    Run "python migrations/migrate.py up"
    Wait-Key
    Note "Decision: map the code (or fix the data), then simply rerun."
    Sql "INSERT INTO order_statuses (id, code) VALUES (4, 'refunded');"
    Run "python migrations/migrate.py up"
    Run "python migrations/verify.py"
    Wait-Key

    Title "Reversible: down, then up again"
    Run "python migrations/migrate.py down"
    Run "python migrations/migrate.py status"
    Run "python migrations/migrate.py up"
    Wait-Key
}

# --- 5. CI ----------------------------------------------------------------------
if ($Section -contains 5) {
    Title "5. CI - switch to the GitHub Actions tab"
    Note "Show: migration safety tests, migrate under 200 live writes, verify, alerts + terraform jobs."
    Wait-Key
}

# --- 6. Container -----------------------------------------------------------------
if ($Section -contains 6) {
    Title "6. Container: migrate job gates the app"
    Run "docker compose up --build -d"
    Run "docker compose ps"
    Run "docker compose logs migrate"
    Run "docker compose exec app id"
    Run "docker images orders-api:local"
    Wait-Key
    Note "Liveness never touches the DB; readiness does:"
    Run "curl.exe -s localhost:8000/livez"
    Run "curl.exe -s localhost:8000/readyz"
    Wait-Key
}

# --- 7. Observability ---------------------------------------------------------------
if ($Section -contains 7) {
    Title "7. Observability: JSON logs with request_id, bounded metrics"
    Run "Invoke-RestMethod -Method Post http://localhost:8000/orders -Headers @{'X-Request-ID'='demo-42'} -ContentType 'application/json' -Body '{`"amount`": 9, `"status`": `"paid`"}'"
    Run "docker compose logs app --no-log-prefix | Select-String 'demo-42'"
    Wait-Key
    Run "curl.exe -s localhost:8000/metrics | Select-String 'http_requests_total\{|orders_created_total\{'"
    Note "Then show observability/alerts.yml in the editor."
    Wait-Key
}

Write-Host "`nDone." -ForegroundColor Green
