<#
.SYNOPSIS
    Rebuild the Sprint 2 demo database in one command.

.DESCRIPTION
    Recreates the database named by -Database (RTS_DB_DEMO by default) on the SQL
    Server started by docker compose, applies every migration and seed, registers the
    POS certificate fingerprints and issues the 13 demo tokens.

    It refuses the development database names (RTS_DB, RTS_DB_TEST), stops at the
    first error, prints no secret and can be run again at any time: the database is
    dropped and recreated on every run, so the stock starts at the seeded 40/25/15.

    It does not edit .env: it prints what the operator still has to set.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -Database RTS_DB_DEMO2
#>
[CmdletBinding()]
param(
    [string]$Database = "RTS_DB_DEMO"
)

$ErrorActionPreference = "Stop"

# --- Repository root and safety checks -------------------------------------

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

if ($Database -notmatch '^[A-Za-z0-9_]{1,64}$') {
    throw "Database name '$Database' is not a plain SQL Server identifier."
}
foreach ($reserved in @("RTS_DB", "RTS_DB_TEST")) {
    if ($Database -ieq $reserved) {
        throw "Refusing to reset '$Database': that is a development database. Use RTS_DB_DEMO or another name."
    }
}

$EnvFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path $EnvFile)) {
    throw "Missing $EnvFile. Copy .env.example to .env and fill in MSSQL_SA_PASSWORD, JWT_SECRET and POS_GATEWAY_SECRET."
}

$Password = $null
Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*MSSQL_SA_PASSWORD\s*=\s*(.+?)\s*$') {
        $Password = $Matches[1].Trim().Trim('"').Trim("'")
    }
}
if ([string]::IsNullOrWhiteSpace($Password)) {
    throw "$EnvFile has no MSSQL_SA_PASSWORD."
}

# --- Helpers ----------------------------------------------------------------

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
    & docker compose exec -T -e "SQLCMDPASSWORD=$Password" sqlserver `
        /opt/mssql-tools18/bin/sqlcmd `
        -S localhost -U sa -C -b -d $DatabaseName -Q $Query
    if ($LASTEXITCODE -ne 0) {
        throw "sqlcmd failed on '$DatabaseName' with exit code $LASTEXITCODE. Is sqlserver healthy?"
    }
}

function Invoke-Migration {
    param([string]$DatabaseName)
    & docker compose run --rm -e "DB_NAME=$DatabaseName" migrate
    if ($LASTEXITCODE -ne 0) {
        throw "the migration failed for '$DatabaseName' with exit code $LASTEXITCODE."
    }
}

function Invoke-MiddlewareScript {
    param([string]$DatabaseName, [string]$Script, [string]$VolumeMode)
    & docker compose run --rm -e "DB_NAME=$DatabaseName" `
        --volume "${PWD}:/repo:$VolumeMode" --workdir /repo `
        middleware python $Script
    if ($LASTEXITCODE -ne 0) {
        throw "'$Script' failed for '$DatabaseName' with exit code $LASTEXITCODE."
    }
}

# --- Rebuild the database ---------------------------------------------------

Write-Host "==> Starting SQL Server"
Invoke-Compose @("up", "-d", "--wait", "sqlserver")

Write-Host "==> Stopping the services that may hold connections"
Invoke-Compose @("stop", "middleware", "pos-gateway")

Write-Host "==> Dropping and recreating $Database"
$quoted = "[$Database]"
Invoke-Sql -Query @"
IF DB_ID(N'$Database') IS NOT NULL
BEGIN
    ALTER DATABASE $quoted SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE $quoted;
END
CREATE DATABASE $quoted;
"@

Write-Host "==> Applying migrations and the demo seed"
Invoke-Migration -DatabaseName $Database

Write-Host "==> Building the middleware image (cached when unchanged)"
Invoke-Compose @("build", "middleware")

Write-Host "==> Registering the POS certificate fingerprints"
Invoke-MiddlewareScript -DatabaseName $Database `
    -Script "scripts/register_pos_certificates.py" -VolumeMode "ro"

Write-Host "==> Issuing the 13 demo tokens"
Invoke-MiddlewareScript -DatabaseName $Database `
    -Script "scripts/issue_demo_tokens.py" -VolumeMode "rw"

# --- What the operator still has to do --------------------------------------

Write-Host ""
Write-Host "Database $Database is ready. The stock is back to the seeded 40/25/15."
Write-Host "Next:"
Write-Host "  1. Set DB_NAME=$Database in .env (never commit .env)."
Write-Host "  2. docker compose up -d --force-recreate --wait middleware pos-gateway"
Write-Host "  3. docker compose run --rm --volume `"`${PWD}:/repo`" --workdir /repo middleware python scripts/demo/sprint2_smoke.py"
Write-Host "  4. Open clients/demo-pos/DemoPos/bin/Debug/net8.0-windows/DemoPos.exe"
