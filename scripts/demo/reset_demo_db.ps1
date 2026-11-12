<#
.SYNOPSIS
    Rebuild the demo databases in one command (Sprint 2, extended by PB-42-7).

.DESCRIPTION
    Recreates the database named by -Database (RTS_DB_DEMO by default) and the HQ
    demo database named by -HqDatabase (RTS_HQ by default) on the SQL Server started
    by docker compose, applies every migration and seed, registers the POS
    certificate fingerprints, issues the 13 demo tokens, loads 90 days of sales
    history and moves the expiry of a few batches so the near-expiry demo has
    something to show on the business date of the run (UTC+7).

    Near-expiry picture after a run, at STORE-DN1 and STORE-DN2 (default thresholds
    Dairy 3, Bakery 2): Fresh milk expires in 2 days, Yogurt in 3 days, Bread
    tomorrow, Sponge cake expired yesterday with stock. Every other early batch is
    moved just outside its window (Dairy 6 days, Bakery 5 days, Dry goods 60 days),
    so raising the Dairy threshold to 7 adds alerts. STORE-DN3 has no alert.

    When .env already has DB_NAME equal to -Database, the script starts the
    middleware, the POS gateway and the HQ demo again and runs the forecast job
    once if it exists. Otherwise it leaves them stopped and says what to do.

    It refuses the development database names (RTS_DB, RTS_DB_TEST), stops at the
    first error, prints no secret and can be run again at any time. It never edits
    .env: -DemoMode prints the lines the operator should set for the demo.

    -NoBuild runs without Internet: it builds and pulls nothing (docker compose
    gets --pull never and --no-build) and stops before touching any database if
    an image of compose.yaml is missing. Build the images the evening before with
    docker compose build middleware hq-demo and docker compose pull sqlserver
    pos-gateway.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -DemoMode

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
#>
[CmdletBinding()]
param(
    [string]$Database = "RTS_DB_DEMO",
    [string]$HqDatabase = "RTS_HQ",
    [switch]$DemoMode,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

# --- Repository root and safety checks -------------------------------------

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

foreach ($name in @($Database, $HqDatabase)) {
    if ($name -notmatch '^[A-Za-z0-9_]{1,64}$') {
        throw "Database name '$name' is not a plain SQL Server identifier."
    }
    foreach ($reserved in @("RTS_DB", "RTS_DB_TEST")) {
        if ($name -ieq $reserved) {
            throw "Refusing to reset '$name': that is a development database. Use RTS_DB_DEMO or another name."
        }
    }
}
if ($Database -ieq $HqDatabase) {
    throw "-Database and -HqDatabase must be different databases."
}

$EnvFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path $EnvFile)) {
    throw "Missing $EnvFile. Copy .env.example to .env and fill in MSSQL_SA_PASSWORD, JWT_SECRET and POS_GATEWAY_SECRET."
}

function Get-EnvValue {
    param([string]$Key)
    $value = $null
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^\s*$Key\s*=\s*(.+?)\s*$") {
            $value = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $value
}

$Password = Get-EnvValue "MSSQL_SA_PASSWORD"
if ([string]::IsNullOrWhiteSpace($Password)) {
    throw "$EnvFile has no MSSQL_SA_PASSWORD."
}
$EnvDbName = Get-EnvValue "DB_NAME"
$EnvHqDbName = Get-EnvValue "HQ_DB_NAME"
if ([string]::IsNullOrWhiteSpace($EnvHqDbName)) { $EnvHqDbName = "RTS_HQ" }

# --- Helpers ----------------------------------------------------------------

# With -NoBuild nothing is pulled or built; a missing image is an error instead.
$PullArgs = if ($NoBuild) { @("--pull", "never") } else { @() }
$UpArgs = if ($NoBuild) { @("--pull", "never", "--no-build") } else { @() }

function Assert-ImagesPresent {
    $images = & docker compose config --images
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose config failed with exit code $LASTEXITCODE. Is Docker Desktop running?"
    }
    $missing = @()
    # Windows PowerShell turns native stderr into errors under "Stop"; the exit code is enough here.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        foreach ($image in ($images | Sort-Object -Unique)) {
            & docker image inspect $image *> $null
            if ($LASTEXITCODE -ne 0) { $missing += $image }
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($missing.Count -gt 0) {
        throw ("-NoBuild: missing image(s) " + ($missing -join ", ") + ". Nothing was changed. " +
            "Where there is Internet, run: docker compose build middleware hq-demo; docker compose pull sqlserver pos-gateway")
    }
    Write-Host "All images of compose.yaml are present: $(($images | Sort-Object -Unique) -join ', ')"
}

function Invoke-Compose {
    param([string[]]$ComposeArgs)
    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') failed with exit code $LASTEXITCODE."
    }
}

function Invoke-Sql {
    param([string]$Query, [string]$DatabaseName = "master")
    # docker compose exec does not pass host environment variables; -e does.
    # -I sets QUOTED_IDENTIFIER, which updates on tables with filtered indexes need.
    & docker compose exec -T -e "SQLCMDPASSWORD=$Password" sqlserver `
        /opt/mssql-tools18/bin/sqlcmd `
        -S localhost -U sa -C -b -I -W -d $DatabaseName -Q $Query
    if ($LASTEXITCODE -ne 0) {
        throw "sqlcmd failed on '$DatabaseName' with exit code $LASTEXITCODE. Is sqlserver healthy?"
    }
}

function Invoke-Migration {
    param([string]$DatabaseName, [string]$HqDatabaseName)
    & docker compose run --rm @PullArgs -e "DB_NAME=$DatabaseName" -e "HQ_DB_NAME=$HqDatabaseName" migrate
    if ($LASTEXITCODE -ne 0) {
        throw "the migration failed for '$DatabaseName' with exit code $LASTEXITCODE."
    }
}

function Invoke-MiddlewareScript {
    param([string]$DatabaseName, [string]$Script, [string]$VolumeMode)
    & docker compose run --rm @PullArgs -e "DB_NAME=$DatabaseName" `
        --volume "${PWD}:/repo:$VolumeMode" --workdir /repo `
        middleware python $Script
    if ($LASTEXITCODE -ne 0) {
        throw "'$Script' failed for '$DatabaseName' with exit code $LASTEXITCODE."
    }
}

function Remove-Database {
    param([string]$Name)
    Invoke-Sql -Query @"
IF DB_ID(N'$Name') IS NOT NULL
BEGIN
    ALTER DATABASE [$Name] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE [$Name];
END
"@
}

# --- Rebuild the databases --------------------------------------------------

if ($NoBuild) {
    Write-Host "==> -NoBuild: checking that every image is already on this machine"
    Assert-ImagesPresent
}

Write-Host "==> Starting SQL Server"
Invoke-Compose (@("up", "-d", "--wait") + $UpArgs + @("sqlserver"))

Write-Host "==> Stopping the services that may hold connections"
Invoke-Compose @("stop", "middleware", "pos-gateway", "hq-demo")

Write-Host "==> Dropping and recreating $Database"
Remove-Database -Name $Database
Invoke-Sql -Query "CREATE DATABASE [$Database];"

Write-Host "==> Dropping $HqDatabase (the migration recreates it with its tables)"
Remove-Database -Name $HqDatabase

Write-Host "==> Applying migrations, the demo seed and the HQ tables"
Invoke-Migration -DatabaseName $Database -HqDatabaseName $HqDatabase

if ($NoBuild) {
    Write-Host "==> -NoBuild: using the existing middleware image"
}
else {
    Write-Host "==> Building the middleware image (cached when unchanged)"
    Invoke-Compose @("build", "middleware")
}

Write-Host "==> Registering the POS certificate fingerprints"
Invoke-MiddlewareScript -DatabaseName $Database `
    -Script "scripts/register_pos_certificates.py" -VolumeMode "ro"

Write-Host "==> Issuing the 13 demo tokens"
Invoke-MiddlewareScript -DatabaseName $Database `
    -Script "scripts/issue_demo_tokens.py" -VolumeMode "rw"

$HistoryLoaded = $false
if ($Database -ieq "RTS_DB_DEMO") {
    Write-Host "==> Loading 90 days of sales history (seed 42)"
    & docker compose run --rm @PullArgs -e "DB_NAME=$Database" `
        --volume "${PWD}:/repo:ro" --workdir /repo/tools/history-generator `
        -e PYTHONPATH=/repo/middleware -e PYTHONDONTWRITEBYTECODE=1 `
        middleware python -m history_generator --database $Database --days 90 --seed 42
    if ($LASTEXITCODE -ne 0) {
        throw "the history generator failed for '$Database' with exit code $LASTEXITCODE."
    }
    $HistoryLoaded = $true
}
else {
    Write-Host "==> Skipping the history: the generator accepts only RTS_DB_DEMO."
}

Write-Host "==> Moving batch expiry dates for the near-expiry demo (business date, UTC+7)"
Invoke-Sql -DatabaseName $Database -Query @"
SET NOCOUNT ON;
SET XACT_ABORT ON;
DECLARE @today date = CAST(DATEADD(hour, 7, SYSUTCDATETIME()) AS date);
BEGIN TRANSACTION;

-- Every early batch of the seed (suffix -1) just outside its default window.
UPDATE b
SET expiry_date = DATEADD(day, CASE p.category WHEN 'Dairy' THEN 6 WHEN 'Bakery' THEN 5 ELSE 60 END, @today)
FROM dbo.product_batch AS b
JOIN dbo.product AS p ON p.sku = b.sku
WHERE b.batch_id = 'B-' + b.store_id + '-' + b.sku + '-1';

-- STORE-DN1 and STORE-DN2: three batches inside their window, one expired with stock.
UPDATE dbo.product_batch
SET expiry_date = DATEADD(day, CASE sku
                                   WHEN 'SKU-0001' THEN 2
                                   WHEN 'SKU-0002' THEN 3
                                   WHEN 'SKU-0004' THEN 1
                                   ELSE -1
                               END, @today)
WHERE store_id IN ('STORE-DN1', 'STORE-DN2')
  AND sku IN ('SKU-0001', 'SKU-0002', 'SKU-0004', 'SKU-0005')
  AND batch_id = 'B-' + store_id + '-' + sku + '-1'
  AND quantity > 0;

IF @@ROWCOUNT <> 8
BEGIN
    ROLLBACK TRANSACTION;
    THROW 50001, 'Expected 8 demo batches at STORE-DN1 and STORE-DN2; the seed has changed.', 1;
END
COMMIT TRANSACTION;
"@

# --- Start the services again when .env already points at this database ----

$ServicesStarted = $false
if ($EnvDbName -ieq $Database -and $EnvHqDbName -ieq $HqDatabase) {
    Write-Host "==> .env has DB_NAME=${Database}, so starting middleware, pos-gateway and hq-demo"
    Invoke-Compose (@("up", "-d", "--force-recreate", "--wait") + $UpArgs + @("middleware", "pos-gateway", "hq-demo"))
    $ServicesStarted = $true
}

$ForecastLine = ""
if ($ServicesStarted) {
    Write-Host "==> Running the forecast job once, if it exists"
    . (Join-Path $PSScriptRoot "_demo_http.ps1")
    $forecast = Invoke-DemoApi -Method POST -Url "https://localhost:8443/api/v1/admin/jobs/forecast/run" `
        -TokenName "admin" -TimeoutSeconds 300
    if ($forecast.Status -eq 200) {
        $ForecastLine = "Forecast job ran."
    }
    elseif ($forecast.Status -eq 404) {
        $ForecastLine = "Forecast skipped: no forecast job on main yet."
    }
    else {
        throw "The forecast job failed with HTTP $($forecast.Status)."
    }
}
else {
    $ForecastLine = "Forecast skipped: the middleware is stopped (DB_NAME in .env is not $Database)."
}

# --- Summary ----------------------------------------------------------------

Write-Host ""
Write-Host "==> Summary of $Database"
Invoke-Sql -DatabaseName $Database -Query @"
SET NOCOUNT ON;
DECLARE @today date = CAST(DATEADD(hour, 7, SYSUTCDATETIME()) AS date);
SELECT store_id AS store, SUM(quantity) AS units, COUNT(*) AS skus
FROM dbo.inventory GROUP BY store_id ORDER BY store_id;

SELECT b.store_id AS store, b.sku, p.category, b.batch_id,
       b.expiry_date, DATEDIFF(day, @today, b.expiry_date) AS days_left, b.quantity,
       CASE WHEN b.expiry_date < @today THEN 'EXPIRED' ELSE 'NEAR_EXPIRY' END AS state
FROM dbo.product_batch AS b
JOIN dbo.product AS p ON p.sku = b.sku
LEFT JOIN dbo.near_expiry_config AS c ON c.category = p.category
WHERE b.quantity > 0
  AND DATEDIFF(day, @today, b.expiry_date) <= COALESCE(c.threshold_days, 3)
ORDER BY b.store_id, b.expiry_date, b.sku;

SELECT COUNT(*) AS history_transactions,
       MIN(CAST(created_at AS date)) AS first_day, MAX(CAST(created_at AS date)) AS last_day
FROM dbo.pos_transaction WHERE txn_id LIKE 'HIST-%';
"@

Write-Host "==> Summary of $HqDatabase"
Invoke-Sql -DatabaseName $HqDatabase -Query @"
SET NOCOUNT ON;
SELECT (SELECT COUNT(*) FROM dbo.hq_sync_batch) AS hq_batches,
       (SELECT COUNT(*) FROM dbo.hq_sales_total) AS hq_total_rows;
"@

Write-Host ""
Write-Host "Database $Database is ready: stock seeded 40/25/15, demo batches moved, HQ $HqDatabase empty."
if (-not $HistoryLoaded) { Write-Host "No history was loaded." }
Write-Host $ForecastLine

if ($DemoMode) {
    Write-Host ""
    Write-Host "Demo mode: set these lines in .env yourself (never commit .env), then restart the middleware:"
    Write-Host "  DB_NAME=$Database"
    Write-Host "  HQ_DB_NAME=$HqDatabase"
    Write-Host "  SYNC_INTERVAL=3600   (when POST /sync/run is on main: batches appear only when the button is pressed)"
    Write-Host "  SYNC_INTERVAL=60     (when it is not: the scheduler syncs every minute)"
    Write-Host "  SYNC_RETRY_BASE_SECONDS=10"
}

Write-Host ""
Write-Host "Next:"
if (-not $ServicesStarted) {
    Write-Host "  - Set DB_NAME=$Database in .env (never commit .env), then run this script again,"
    Write-Host "    or: docker compose up -d --force-recreate --wait middleware pos-gateway hq-demo"
}
Write-Host "  - Smoke check: docker compose run --rm --no-deps --volume `"`${PWD}:/repo`" --workdir /repo middleware python scripts/demo/sprint2_smoke.py"
Write-Host "  - Console on machine S: clients/demo-console/DemoConsole/bin/Debug/net8.0-windows/DemoConsole.exe"
Write-Host "  - Demo POS on machines A and B: clients/demo-pos/DemoPos/bin/Debug/net8.0-windows/DemoPos.exe"
