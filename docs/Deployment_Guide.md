# RetailSync Deployment Guide

Operational guide for setting up, running, resetting, backing up, testing, and troubleshooting RetailSync on a new machine or multi-machine local network (PB-42-1).

> **Note:** A dedicated user guide for the WinForms Staff App (`clients/staff-app/`) will be added in Sprint 4.

## Table of Contents

1. [System Topology](#1-system-topology)
2. [Prerequisites](#2-prerequisites)
3. [Environment Variables (`.env`)](#3-environment-variables-env)
4. [Certificates and Demo Tokens](#4-certificates-and-demo-tokens)
5. [Database Migration and Seed](#5-database-migration-and-seed)
6. [Starting the Docker Stack](#6-starting-the-docker-stack)
7. [Private-Network / LAN Setup (Multi-Machine Demo)](#7-private-network--lan-setup-multi-machine-demo)
8. [Demo Reset (`reset_demo_db.ps1`)](#8-demo-reset-reset_demo_dbps1)
9. [Database Backup and Restore](#9-database-backup-and-restore)
10. [Running All Test Suites](#10-running-all-test-suites)
11. [Troubleshooting (Sprint 2 & Sprint 3 Demo Notes)](#11-troubleshooting-sprint-2--sprint-3-demo-notes)

---

## 1. System Topology

```text
POS terminal / Demo POS ──(TLS 1.2+, client cert, :9443)──> pos-gateway (nginx) ──> middleware (:8443) ──> sqlserver (:1433)
Staff / Admin / Auditor ──(TLS 1.2+, JWT, :8443)──────────────────────────────────> middleware (:8443)
middleware ──(TLS 1.2+, service JWT)──────────────────────────────────────────────> hq-demo (:9000) ────> sqlserver (:1433)
```

| Service (`compose.yaml`) | Image / Build | Host Binding (default) | Purpose |
|---|---|---|---|
| `sqlserver` | `mcr.microsoft.com/mssql/server:2022-latest` | `127.0.0.1:14333 -> 1433` | Stores `RTS_DB` (dev), `RTS_DB_TEST` (tests), `RTS_DB_DEMO` (demo), `RTS_HQ` / `RTS_HQ_TEST` (HQ) |
| `migrate` | Same SQL Server image | One-shot container | Runs forward-only migrations and idempotent seeds via `database/migrate.sh` |
| `middleware` | `./middleware` (Python 3.12 + ODBC Driver 18) | `${MIDDLEWARE_BIND_ADDRESS:-127.0.0.1}:8443 -> 8443` | Regional FastAPI service over HTTPS (`MTLS_REQUIRED=true`, `SCHEDULER_ENABLED=true`) |
| `pos-gateway` | `nginx:1.28.0-alpine` | `${POS_BIND_ADDRESS:-127.0.0.1}:9443 -> 9443` | Mutual TLS terminator; forwards only `POST /api/v1/pos/events` (`deploy/nginx/pos-gateway.conf.template`) |
| `hq-demo` | `./hq-demo` (Python 3.12 + ODBC Driver 18) | `127.0.0.1:9000 -> 9000` | Simulated HQ service with demo fault modes (`ONLINE`, `OFFLINE`, `ERROR`, `SLOW`, `DROP_ACK`) |

---

## 2. Prerequisites

| Requirement | Version / Notes | Needed For |
|---|---|---|
| Operating System | Windows 10/11 (64-bit) for WinForms clients; Linux/macOS supported for Docker stack | Full stack (`DemoPos` and `DemoConsole` are Windows-only WinForms) |
| Docker Desktop | Using **Linux containers** backend | `sqlserver`, `migrate`, `middleware`, `pos-gateway`, `hq-demo` |
| Git & Git Bash | Includes `openssl` (required on Windows; avoid WSL `bash` when running cert scripts) | Cloning repo, `scripts/generate_dev_certs.sh`, `scripts/check_pos_tls.sh` |
| Python | 3.12 (64-bit) | Native `uvicorn`, native `pytest`, host-side helper scripts (not required if running everything inside Docker) |
| Microsoft ODBC Driver 18 for SQL Server | 64-bit | Native Python database connections only (the Docker images install Linux `msodbcsql18` automatically) |
| .NET 8 SDK | .NET 8 SDK (or newer SDK with .NET 8 desktop runtime; verify with `dotnet --list-sdks`) | Building and testing `clients/demo-pos/` and `clients/demo-console/` |

A local SQL Server installation and Visual Studio are **not** required.

---

## 3. Environment Variables (`.env`)

Copy `.env.example` to `.env` in the repository root and populate local secrets. **Never commit `.env`.**

```powershell
Copy-Item .env.example .env
```

Settings load from the repository root `.env`, then a working-directory `.env` if present. Process environment variables take precedence over `.env`.

### Complete Variable Reference (`.env.example`)

| Variable | Default in `.env.example` | Compose Override (`compose.yaml`) | Purpose |
|---|---|---|---|
| `MSSQL_SA_PASSWORD` | `replace-with-a-strong-password` | Passed as `MSSQL_SA_PASSWORD` / `SQLCMDPASSWORD` | SQL Server `sa` password (no code default; must meet SQL Server complexity rules) |
| `SQLSERVER_PORT` | `14333` | Overridden to `1433` inside containers | Host port published by `sqlserver` (`127.0.0.1:<port>:1433`) for native clients |
| `DB_HOST` | `127.0.0.1` | Overridden to `sqlserver` inside containers | SQL Server host for native runs |
| `DB_NAME` | `RTS_DB` | Uses `.env` (default `RTS_DB`) | Active middleware database (`RTS_DB` for dev, `RTS_DB_DEMO` for demos) |
| `TEST_DB_NAME` | `RTS_DB_TEST` | Uses `.env` or `--env` override | Database used by `middleware` pytest; must end in `_TEST` and differ from `DB_NAME` |
| `HQ_DB_NAME` | `RTS_HQ` | Uses `.env` (default `RTS_HQ`) | Database used by `hq-demo` (`RTS_HQ_TEST` for `hq-demo` pytest) |
| `HQ_URL` | `http://localhost:9000/api/v1` | Overridden to `https://hq-demo:9000/api/v1` | Base URL the middleware sends sync batches to |
| `HQ_CA_FILE` | `.certs/ca.crt` | Overridden to `/certs/ca.crt` | CA bundle trusted by middleware when calling `hq-demo` |
| `HQ_TIMEOUT_SECONDS` | `3` | Overridden to `3` | HTTP timeout (seconds) for middleware-to-HQ sync calls |
| `HQ_JWT_SECRET` | `replace-with-a-long-random-secret` | Passed to `middleware` and `hq-demo` | Shared HS256 secret for middleware-to-HQ service JWT (`sub: rts-middleware`, `role: MIDDLEWARE`) |
| `SYNC_INTERVAL` | `3600` | Uses `.env` | Seconds between scheduled `aggregation` runs; `sync-send` runs at least this often (`3600` in prod/manual demo, `60` for auto-cycle demo) |
| `SYNC_RETRY_BASE_SECONDS` | `60` | Uses `.env` | Base exponential backoff in seconds for failed HQ sync deliveries (`10` in demos) |
| `SYNC_SEND_POLL_SECONDS` | `30` | Uses `.env` | `sync-send` runs every `min(SYNC_INTERVAL, SYNC_SEND_POLL_SECONDS)` seconds, so a retry goes out at most one poll after it is due (5 to 3600) |
| `JWT_SECRET` | `replace-with-a-long-random-secret` | Uses `.env` | HS256 signing key for POS, Staff, Manager, Admin, Auditor, and HQ operator JWTs |
| `MTLS_REQUIRED` | `false` | Overridden to `true` in `middleware` | Enforces `X-Gateway-Secret` and client certificate fingerprint check on `POST /api/v1/pos/events` |
| `POS_GATEWAY_SECRET` | `replace-with-a-long-random-secret` | Passed to `middleware` and `pos-gateway` | Shared secret nginx injects as `X-Gateway-Secret` so POS events cannot bypass port 9443 |
| `POS_LOCK_TIMEOUT_MS` | `2000` | Uses `.env` | Max wait (ms, positive integer) per SQL Server lock on the POS event path before returning `503 SERVICE_UNAVAILABLE` |
| `SCHEDULER_ENABLED` | `false` | Overridden to `true` in `middleware` | Enables background scheduler (`aggregation`, `near-expiry`, `forecast`, `recommendation`, `sync-send`) |
| `NEAR_EXPIRY_DEFAULT_DAYS` | `3` | Uses `.env` | Fallback alert window (0–3650 days) for categories without a `near_expiry_config` row |
| `POS_BIND_ADDRESS` | `127.0.0.1` | Used for `pos-gateway` port `9443` | Private host interface for POS gateway (never bind a public internet address) |
| `MIDDLEWARE_BIND_ADDRESS` | `127.0.0.1` | Used for `middleware` port `8443` | Private host interface for middleware API |

Additional optional setting supported by `middleware/app/core/config.py`:

| Variable | Default | Purpose |
|---|---|---|
| `BUSINESS_UTC_OFFSET_HOURS` | `7` | Local business timezone offset (`-12` to `14`, UTC+7 for Vietnam) used by `clock.today_local()` and daily job times |

### Generating Strong Random Secrets (PowerShell)

Run in PowerShell to generate 32-byte hex values for `JWT_SECRET`, `POS_GATEWAY_SECRET`, and `HQ_JWT_SECRET` without printing them into Git history:

```powershell
foreach ($key in @("JWT_SECRET", "POS_GATEWAY_SECRET", "HQ_JWT_SECRET")) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    Write-Host "$key=$(-join ($bytes | ForEach-Object { $_.ToString('x2') }))"
}
```

Paste the generated values (plus a strong `MSSQL_SA_PASSWORD`) into `.env`.

---

## 4. Certificates and Demo Tokens

All Docker services serve HTTPS (TLS 1.2 / 1.3 only), and POS terminals authenticate to `pos-gateway` with mutual TLS client certificates.

### 4.1. Generate Development Certificates

Run `scripts/generate_dev_certs.sh` via **Git Bash** (in PowerShell, plain `bash` may invoke WSL instead of Git Bash):

```powershell
& "$env:ProgramFiles\Git\bin\bash.exe" scripts/generate_dev_certs.sh
```

This creates `.certs/` (git-ignored; never commit):

| Path | Purpose |
|---|---|
| `.certs/ca.key`, `.certs/ca.crt` | Development Certificate Authority (valid 3650 days) |
| `.certs/server.key`, `.certs/server.crt` | Server cert for `middleware`, `pos-gateway`, `hq-demo` (SANs: `localhost`, `127.0.0.1`, `middleware.retailsync.local`, `middleware`, `hq-demo`, `pos-gateway`, plus `EXTRA_SANS` if set) |
| `.certs/pos/<pos_id>.key`, `.certs/pos/<pos_id>.crt` | Client certs (`CN=<pos_id>`) for the 6 seeded terminals (`POS-DN1-01` .. `POS-DN3-02`) |

Re-running the script preserves existing valid certificates. Only re-issue what is needed:
- Add a LAN IP SAN without replacing the CA: `EXTRA_SANS=IP:192.168.1.10 bash scripts/generate_dev_certs.sh`
- Force full replacement of CA, server, and client certificates: `RENEW=1 bash scripts/generate_dev_certs.sh`

> **Important:** Whenever client certificates are generated or renewed (or when switching to a fresh database), you must re-register their SHA-256 fingerprints in `dbo.pos_terminal`.

Each Docker service mounts only the certificate files it uses (read-only); `.certs/ca.key` and `.certs/pos/*.key` are never mounted into any container:

| Service | Mounted `/certs/*` files (`:ro`) |
|---|---|
| `middleware` | `ca.crt`, `server.crt`, `server.key` |
| `pos-gateway` | `ca.crt`, `server.crt`, `server.key` |
| `hq-demo` | `server.crt`, `server.key` |

Run `scripts/generate_dev_certs.sh` **before** the first `docker compose up`, so Docker mounts existing files rather than creating empty directories at missing paths.

### 4.2. Register POS Fingerprints and Issue Demo JWTs

After building `middleware` and migrating the target database (Section 5), run from the repository root:

```powershell
docker compose build middleware
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python scripts/register_pos_certificates.py
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/issue_demo_tokens.py
```

- `scripts/register_pos_certificates.py` writes each terminal's DER SHA-256 fingerprint into `pos_terminal.cert_fingerprint` in `DB_NAME` (from `.env`).
- `scripts/issue_demo_tokens.py` writes 13 JWTs (`staff_dn1..3`, `manager_dn1`, `admin`, `auditor`, `hq_operator`, and `POS-DN1-01..POS-DN3-02`) to `.tokens/demo_tokens.json` (git-ignored; prints token names only).

---

## 5. Database Migration and Seed

Start SQL Server and apply all forward-only migrations and idempotent seeds:

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm migrate
```

What `database/migrate.sh` does:
1. Creates `DB_NAME` (default `RTS_DB`) if absent and tracks applied versions in `dbo.schema_migration`.
2. Applies `database/migrations/001_core.sql`, `002_batches_alerts_forecast.sql`, and `003_recommendations.sql` once each in filename order.
3. Executes idempotent seed scripts `database/seed/001_demo_stores_pos.sql` through `004_near_expiry_defaults.sql` (3 stores, 6 POS terminals, 9 SKUs, opening stock 40/25/15 per SKU, default guardrail rules, near-expiry thresholds).
4. Creates `HQ_DB_NAME` (default `RTS_HQ`) and applies `database/hq/001_hq_tables.sql` once.

Re-running `docker compose run --rm migrate` prints only `Database is up to date` and `HQ database RTS_HQ is up to date`.

### Verify Database Schema and Seed Counts

```powershell
@'
SET NOCOUNT ON;
SELECT COUNT(*) AS application_tables FROM sys.tables WHERE name <> 'schema_migration';
SELECT COUNT(*) AS migration_tables FROM sys.tables WHERE name = 'schema_migration';
SELECT COUNT(*) AS stores FROM dbo.store;
SELECT COUNT(*) AS pos_terminals FROM dbo.pos_terminal;
SELECT version FROM dbo.schema_migration ORDER BY version;
'@ | docker compose exec -T sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b -d RTS_DB'
```

Expected on a clean setup: **19** application tables, **1** `schema_migration` table, **3** stores, **6** POS terminals, and **3** applied migration files (`001_core.sql`, `002_batches_alerts_forecast.sql`, `003_recommendations.sql`).

### Create the Test Databases (`RTS_DB_TEST` and `RTS_HQ_TEST`)

```powershell
docker compose run --rm -e DB_NAME=RTS_DB_TEST -e HQ_DB_NAME=RTS_HQ_TEST migrate
```

---

## 6. Starting the Docker Stack

Build the application images, pull external images, and start the full stack:

```powershell
docker compose build middleware hq-demo
docker compose pull sqlserver pos-gateway
docker compose up -d --wait sqlserver middleware pos-gateway hq-demo
docker compose ps
```

### Startup Order and Health Checks (`compose.yaml`)

`compose.yaml` enforces the startup chain automatically:

1. `sqlserver` starts and passes its `sqlcmd SELECT 1` healthcheck.
2. `migrate` runs `database/migrate.sh` to completion (`service_completed_successfully`) before `middleware` or `hq-demo` starts, so the middleware scheduler never runs catch-up jobs against missing tables or unseeded data.
3. `middleware` starts and passes its HTTPS healthcheck (`curl -fsS --cacert /certs/ca.crt https://localhost:8443/api/v1/health`, interval 5 s, 20 retries, 10 s start period); `hq-demo` starts in parallel after `migrate`.
4. `pos-gateway` waits for `middleware` (`service_healthy`) before exposing port `9443`.

Because `middleware` defines a healthcheck, `docker compose up -d --wait middleware pos-gateway hq-demo` does not return until `middleware` is actively serving HTTPS on port `8443`.

### Verify Health and TLS / mTLS

1. **Middleware HTTPS health (port 8443):**
   ```powershell
   curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://localhost:8443/api/v1/health
   ```
   Expected: `{"status":"ok"}`. (`--ssl-no-revoke` is required on Windows because Schannel checks CRL/OCSP endpoints that the local development CA does not publish.)

2. **HQ demo HTTPS health (port 9000):**
   ```powershell
   curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://localhost:9000/api/v1/health
   ```
   Expected: `{"status":"ok"}`.

3. **POS gateway TLS protocol enforcement (TLS 1.2 & 1.3 pass; TLS 1.1 refused):**
   ```powershell
   & "$env:ProgramFiles\Git\bin\bash.exe" scripts/check_pos_tls.sh
   ```

4. **POS gateway route restriction (only `POST /api/v1/pos/events` forwarded; path traversal and other methods refused):**
   ```powershell
   docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo --entrypoint bash middleware scripts/check_pos_gateway.sh
   ```

5. **Sending a manual POS test event over mTLS on Windows:** Windows `curl.exe` uses Schannel and cannot send PEM/PKCS#12 client certificates to port 9443. Use either Python `ssl`/`urllib` on the host or OpenSSL `curl` inside the `middleware` image (see `README.md`, section "Send a test event with a client certificate on Windows").

### Scheduled Background Jobs (`middleware`)

When `SCHEDULER_ENABLED=true` (default in Docker), `middleware/app/jobs/registry.py` runs:

| Job Name | Schedule | Purpose |
|---|---|---|
| `aggregation` | Every `SYNC_INTERVAL` seconds | Aggregates unbatched POS transactions per store into `sync_batch` (`PENDING`) |
| `near-expiry` | Daily at `00:30` business time (UTC+7) | Scans sellable batches against category thresholds and creates/updates `near_expiry_alert` |
| `forecast` | Daily at `01:00` business time (UTC+7) | Trains demand model on historical sales and writes 7-day SKU forecasts |
| `recommendation` | Daily at `02:00` business time (UTC+7) | Expires invalid `PENDING` recommendations, generates new recommendations from near-expiry alerts and forecasts, and validates them through active guardrail rules |
| `sync-send` | Every `min(SYNC_INTERVAL, SYNC_SEND_POLL_SECONDS)` seconds | Sends due `PENDING` batches oldest-first to `HQ_URL`; waits while the oldest unfinished batch is `SENT` or not yet due |

Daily jobs catch up automatically on startup if their scheduled time has already passed on the current business date, and can be triggered manually via `POST /api/v1/admin/jobs/{name}/run` with an `Admin` token.

### Native Local Development (Optional)

For fast local iteration without Docker TLS (`MTLS_REQUIRED=false`, HTTP port `8000`):

```powershell
Set-Location middleware
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Verify with `Invoke-RestMethod http://localhost:8000/api/v1/health`.

---

## 7. Private-Network / LAN Setup (Multi-Machine Demo)

For a multi-machine demo over a dedicated hotspot or private LAN (Machine **S** hosting Docker + Demo Console; Machines **A** and **B** running `DemoPos` and cross-store scripts):

### 7.1. Prepare Machine S (Server)

1. Connect Machine S to the private hotspot/router, assign a static private IP (e.g., `192.168.1.10`), and set the Windows network profile to **Private**.
2. Set the bind addresses in `.env` (never use a public internet IP):
   ```dotenv
   POS_BIND_ADDRESS=192.168.1.10
   MIDDLEWARE_BIND_ADDRESS=192.168.1.10
   ```
3. Reissue **only** the server certificate with the LAN IP in SAN (do **not** regenerate the CA, or A and B will need a new `ca.crt`):
   ```powershell
   & "$env:ProgramFiles\Git\bin\bash.exe" -c "EXTRA_SANS=IP:192.168.1.10 bash scripts/generate_dev_certs.sh"
   ```
4. Recreate and start the services so Docker binds the private IP and loads the new server certificate:
   ```powershell
   docker compose up -d --force-recreate --wait middleware pos-gateway hq-demo
   ```
5. Open Windows Firewall inbound ports `8443` and `9443` for the **Private** profile only (PowerShell **as Administrator**):
   ```powershell
   .\scripts\demo\open_firewall.ps1
   ```
   Close the firewall rules after the demo:
   ```powershell
   .\scripts\demo\close_firewall.ps1
   ```

### 7.2. Export Minimal Credentials for Machines A and B

Run after the **final** `reset_demo_db.ps1` (each reset issues fresh tokens):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/export_terminal_tokens.ps1 -Terminal POS-DN1-01 -Staff staff_dn1 -Out .\out\A
powershell -ExecutionPolicy Bypass -File scripts/demo/export_terminal_tokens.ps1 -Terminal POS-DN2-01 -Staff staff_dn2 -Out .\out\B
```

Security guarantees enforced by `export_terminal_tokens.ps1`:
- Exports only `.certs/ca.crt`, `.certs/pos/<terminal>.crt`, `.certs/pos/<terminal>.key`, and a trimmed `.tokens/demo_tokens.json` containing **only** that terminal's POS token and its own store's Staff token.
- Refuses `admin`, `auditor`, `hq_operator`, and cross-store Staff tokens.
- Never prints token contents. Delete `.\out\` on Machine S immediately after copying to Machines A and B.

### 7.3. Configure Machines A and B (Client)

1. Build `DemoPos` while Internet is available:
   ```powershell
   dotnet build clients/demo-pos/DemoPos/DemoPos.csproj -c Debug
   ```
2. Copy the contents of `out\A` (or `out\B`) into the repository root of the clone on that machine.
3. Create `clients/demo-pos/DemoPos/appsettings.Local.json` (git-ignored) pointing to Machine S's IP (must match the server certificate SAN) and listing only that machine's terminal:
   ```json
   {
     "PosBaseUrl": "https://192.168.1.10:9443/api/v1",
     "MonitorBaseUrl": "https://192.168.1.10:8443/api/v1",
     "Terminals": [
       { "StoreId": "STORE-DN1", "StoreName": "Cửa hàng Hải Châu", "PosId": "POS-DN1-01" }
     ]
   }
   ```
4. Verify connectivity from A and B before starting:
   ```powershell
   curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://192.168.1.10:8443/api/v1/health
   dotnet run --project clients/demo-pos/DemoPos/DemoPos.csproj --no-build
   ```
   Missing the `auditor` token on A/B is expected: the Audit panel displays a notice and stays empty while sales and inventory monitoring work normally.

---

## 8. Demo Reset (`reset_demo_db.ps1`)

`scripts/demo/reset_demo_db.ps1` rebuilds `RTS_DB_DEMO` and `RTS_HQ` cleanly in ~45 seconds. It **refuses** `RTS_DB` and `RTS_DB_TEST` by design and never edits `.env`.

### Standard and Offline Usage

```powershell
# Print recommended .env demo values (DB_NAME=RTS_DB_DEMO, SYNC_RETRY_BASE_SECONDS=10, etc.)
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -DemoMode

# Full reset (rebuilds middleware image if changed)
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1

# Offline reset (no Internet: fails fast before touching DB if any Compose image is missing)
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
```

Before an offline demo, pre-build and pull images while online:

```powershell
docker compose build middleware hq-demo
docker compose pull sqlserver pos-gateway
```

### What `reset_demo_db.ps1` Produces

1. Stops `middleware`, `pos-gateway`, and `hq-demo`.
2. Drops and recreates `RTS_DB_DEMO` and `RTS_HQ`, applies all migrations and seeds.
3. Registers POS client certificate fingerprints into `RTS_DB_DEMO` and issues 13 fresh JWTs into `.tokens/demo_tokens.json`.
4. Loads 90 days of deterministic simulated sales history (`HIST-`, seed `42`, **2,320** rows) into `RTS_DB_DEMO`.
5. Shifts batch expiry dates relative to today's business date (UTC+7):
   - Opening stock: `STORE-DN1` = 360 units (40/SKU), `STORE-DN2` = 225 (25/SKU), `STORE-DN3` = 135 (15/SKU).
   - 8 near-expiry/expired batches across `STORE-DN1` and `STORE-DN2` (Bread +1d, Fresh milk +2d, Yogurt +3d, Sponge cake `-1d` expired with stock); `STORE-DN3` has zero open alerts until thresholds are raised.
   - `RTS_HQ` starts empty (`hq_batches = 0`, `hq_total_rows = 0`).
6. If `.env` already sets `DB_NAME=RTS_DB_DEMO` and `HQ_DB_NAME=RTS_HQ`, restarts `middleware`, `pos-gateway`, `hq-demo` and triggers `POST /api/v1/admin/jobs/forecast/run`.

### Smoke Check and Post-Demo Cleanup

Verify the demo stack with the 14-step smoke script, then run `reset_demo_db.ps1` **one final time** (because the smoke script writes demo transactions):

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/demo/sprint2_smoke.py
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
```

Expected smoke result: `ALL CHECKS PASSED`.

After the demo finishes, restore `.env` to development defaults (`DB_NAME=RTS_DB`, `SYNC_INTERVAL=3600`, `SYNC_RETRY_BASE_SECONDS=60`, `POS_BIND_ADDRESS=127.0.0.1`, `MIDDLEWARE_BIND_ADDRESS=127.0.0.1`), close firewall rules (`scripts/demo/close_firewall.ps1`), and recreate the services:

```powershell
docker compose up -d --force-recreate --wait middleware pos-gateway hq-demo
```

---

## 9. Database Backup and Restore

SQL Server data lives in the named Docker volume `retailsync_sqlserver_data` (`/var/opt/mssql`).

> **Warning:** Never run `docker compose down -v` casually — `-v` deletes `retailsync_sqlserver_data` and destroys `RTS_DB`, `RTS_HQ`, and all databases inside the container.

### 9.1. Backup `RTS_DB` and `RTS_HQ` to `.bak` Files

Create a backup directory inside the container, run `BACKUP DATABASE` with compression and checksum, and copy the files to a host folder outside Git (for example `.\backups\` or a safe local path):

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
New-Item -ItemType Directory -Force .\backups | Out-Null

docker compose exec -T sqlserver mkdir -p /var/opt/mssql/backup

# Backup RTS_DB
@"
BACKUP DATABASE [RTS_DB]
TO DISK = N'/var/opt/mssql/backup/RTS_DB_$stamp.bak'
WITH FORMAT, INIT, COMPRESSION, CHECKSUM, NAME = N'RTS_DB-Full-$stamp';
"@ | docker compose exec -T sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b'

# Backup RTS_HQ
@"
BACKUP DATABASE [RTS_HQ]
TO DISK = N'/var/opt/mssql/backup/RTS_HQ_$stamp.bak'
WITH FORMAT, INIT, COMPRESSION, CHECKSUM, NAME = N'RTS_HQ-Full-$stamp';
"@ | docker compose exec -T sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b'

# Copy backups out of the container to host
docker compose cp "sqlserver:/var/opt/mssql/backup/RTS_DB_$stamp.bak" ".\backups\RTS_DB_$stamp.bak"
docker compose cp "sqlserver:/var/opt/mssql/backup/RTS_HQ_$stamp.bak" ".\backups\RTS_HQ_$stamp.bak"
```

Verify backup integrity before relying on it:

```powershell
@"
RESTORE VERIFYONLY
FROM DISK = N'/var/opt/mssql/backup/RTS_DB_$stamp.bak'
WITH CHECKSUM;
"@ | docker compose exec -T sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b'
```

> Keep `.bak` files outside tracked Git directories (never commit backups).

### 9.2. Restore from a `.bak` File

Stop services holding connections, copy the `.bak` file into the container, restore with `SINGLE_USER` + `REPLACE`, and restart services:

```powershell
$bakFile = "RTS_DB_20261119_080000.bak"   # replace with your backup filename

docker compose stop middleware pos-gateway hq-demo
docker compose exec -T sqlserver mkdir -p /var/opt/mssql/backup
docker compose cp ".\backups\$bakFile" "sqlserver:/var/opt/mssql/backup/$bakFile"

@"
IF DB_ID(N'RTS_DB') IS NOT NULL
    ALTER DATABASE [RTS_DB] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
RESTORE DATABASE [RTS_DB]
FROM DISK = N'/var/opt/mssql/backup/$bakFile'
WITH REPLACE, STATS = 10;
ALTER DATABASE [RTS_DB] SET MULTI_USER;
"@ | docker compose exec -T sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b -d master'

docker compose up -d --wait middleware pos-gateway hq-demo
```

Repeat with `RTS_HQ` and its corresponding `.bak` file if restoring HQ state as well.

---

## 10. Running All Test Suites

All database tests use dedicated `_TEST` databases and never write to `RTS_DB` or `RTS_HQ`. Ensure `sqlserver` is healthy and both test databases are migrated first:

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm -e DB_NAME=RTS_DB_TEST -e HQ_DB_NAME=RTS_HQ_TEST migrate
```

### 10.1. Middleware Tests (Container — Authoritative)

Pass `--no-deps` (so `middleware`'s `depends_on: migrate` does not run `migrate` against `.env`'s default `DB_NAME`) together with `TEST_DB_NAME=RTS_DB_TEST` and `DB_NAME=RTS_DB_NOWRITE` (a non-existent DB name) so any stray `SessionLocal()` call fails immediately instead of writing to `RTS_DB`. Mount the entire repository root because tests read `database/seed/` and `scripts/`:

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/middleware --env PYTHONDONTWRITEBYTECODE=1 --env TEST_DB_NAME=RTS_DB_TEST --env DB_NAME=RTS_DB_NOWRITE middleware sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

Expected: all tests **passed**, **0 skipped**.

Native run (requires Python 3.12 + 64-bit ODBC Driver 18):

```powershell
Set-Location middleware
.\.venv\Scripts\python.exe -m pytest -q
```

Health-only check without SQL Server: `python -m pytest tests/test_health.py`.

### 10.2. HQ Demo Tests (Container)

Runs exclusively against `RTS_HQ_TEST` (pass `--no-deps` so `migrate` is not triggered against `.env`'s default `DB_NAME`):

```powershell
docker compose run --rm --no-deps -e HQ_DB_NAME=RTS_HQ_TEST --volume "${PWD}/hq-demo:/app" --workdir /app hq-demo sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

### 10.3. .NET Client Tests (Windows)

```powershell
dotnet test clients/demo-pos/DemoPos.sln
dotnet test clients/demo-console/DemoConsole.sln
```

### 10.4. Supporting Tool Tests (POS Simulator & History Generator)

```powershell
# POS event simulator (network-free)
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONPATH=/repo/middleware:/repo/tools/pos-simulator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r requirements.txt -r /repo/middleware/requirements-dev.txt && python -m pytest -p no:cacheprovider -q'

# History generator (against RTS_DB_TEST)
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/tools/history-generator --env PYTHONPATH=/repo/middleware:/repo/tools/history-generator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r /repo/middleware/requirements-dev.txt && python -m pytest -p no:cacheprovider -p tests.conftest -q tests'
```

---

## 11. Troubleshooting (Sprint 2 & Sprint 3 Demo Notes)

| Symptom | Root Cause | Resolution |
|---|---|---|
| `curl.exe` fails on HTTPS with revocation / Schannel error | Windows `curl.exe` uses Schannel and checks CRL/OCSP, which the dev CA does not host | Always add `--ssl-no-revoke --cacert .certs/ca.crt` when calling port `8443` or `9000` with Windows `curl.exe` |
| `curl.exe --cert ... --key ...` fails on port `9443` | Windows Schannel does not send PEM/PKCS#12 client certs this way | Use Python `ssl`/`urllib` on Windows or OpenSSL `curl` inside the `middleware` container (`README.md`) |
| `docker compose up` fails to bind `8443`/`9443`, or `reset_demo_db.ps1` cannot reach `localhost:8443` | `POS_BIND_ADDRESS` / `MIDDLEWARE_BIND_ADDRESS` in `.env` is still set to an old hotspot/LAN IP (e.g., `10.83.148.200` or `192.168.x.x`) that is not active on this network, or binds only that IP instead of `127.0.0.1` | Set both back to `127.0.0.1` in `.env` for local runs (or override in the shell session) and run `docker compose up -d --force-recreate --wait middleware pos-gateway` |
| Machines A or B cannot reach Machine S on hotspot | Wrong network profile (Public vs Private), firewall closed, IP changed, or phone hotspot enables client isolation | Verify all 3 machines are on the same hotspot, test `ping <IP-S>`, switch Machine S adapter to **Private**, run `scripts/demo/open_firewall.ps1` as Administrator; if IP changed, re-run `EXTRA_SANS=IP:<new-IP> bash scripts/generate_dev_certs.sh` and update `appsettings.Local.json`; if phone blocks peer-to-peer traffic, switch to a backup hotspot or run 2 `DemoPos` windows locally on Machine S |
| POS returns `403 FORBIDDEN` through port `9443` | Terminal cert fingerprint not registered in the active `DB_NAME`, wrong `POS_GATEWAY_SECRET`, cert/terminal mismatch, or request sent directly to `8443` | Check `POS_GATEWAY_SECRET` in `.env`, re-run `scripts/register_pos_certificates.py` (or `reset_demo_db.ps1`) against the active `DB_NAME`, and verify the client cert matches `pos_id` |
| POS gateway returns `400 Bad Request` (nginx HTML) | Request arrived at port `9443` without a valid CA-issued client certificate | Confirm `.certs/pos/<pos_id>.crt` and `.key` exist and were issued by the current `.certs/ca.crt` |
| All API calls return `401 UNAUTHORIZED` | Stale `.tokens/demo_tokens.json` or `JWT_SECRET` changed after tokens were issued | Re-run `scripts/issue_demo_tokens.py` (or `reset_demo_db.ps1`) and re-export tokens to Machines A/B if on LAN |
| `docker compose up middleware` exits immediately or fails mounting `/certs/*` | Missing `.certs/ca.crt`, `.certs/server.crt`, or `.certs/server.key` (Docker creates empty directories if a file bind-mount source is missing) | Remove any accidental empty directories under `.certs/`, then run `& "$env:ProgramFiles\Git\bin\bash.exe" scripts/generate_dev_certs.sh` |
| `middleware` stays `unhealthy` (`curl` healthcheck TLS error) | `.certs/server.crt` was not signed by `.certs/ca.crt` | Re-run `& "$env:ProgramFiles\Git\bin\bash.exe" scripts/generate_dev_certs.sh`, then recreate the services (`docker compose up -d --force-recreate --wait middleware pos-gateway hq-demo`) |
| `Access denied` when `DemoPos` loads a client certificate | Restricted workspace/sandbox blocks Windows certificate store writes during PKCS#12 re-import | Copy the built output outside the restricted directory (e.g., `%TEMP%\DemoPos`) or run on a standard Windows desktop session |
| `IM002` / `Can't open lib` in native Python | 64-bit Microsoft ODBC Driver 18 for SQL Server is not installed on Windows | Install 64-bit ODBC Driver 18, or run Python commands inside the `middleware` Docker container |
| SQL Server login failure or SQLPAL startup error | Changing `MSSQL_SA_PASSWORD` in `.env` does not change the password inside an existing `sqlserver_data` volume; or an older/corrupted volume fails SQLPAL startup | Restore the original `MSSQL_SA_PASSWORD` matching the volume, or start an isolated Compose project (`docker compose -p retailsync-fresh ...`) without deleting an existing data volume |
| Demo Console buttons are grayed out or a tab shows a red error | Route not deployed yet (404; console re-probes every 30 s) or `middleware`/`sqlserver` still starting (retries every 3 s). Note: clicking **Chạy dự báo** on 404 disables that button until the console restarts | Wait for `docker compose ps` healthy status; restart `DemoConsole.exe` after deploying new routes |
| Hotspot unstable during WAN-outage demo (Act 4) | Phone Wi-Fi drops unpredictably | Run `DemoPos` locally on Machine S and simulate the WAN outage deterministically with `docker compose stop pos-gateway` and `docker compose start pos-gateway` |
| `POST /api/v1/pos/events` returns `503 SERVICE_UNAVAILABLE` with `SQL 1222` in logs | A database lock wait exceeded `POS_LOCK_TIMEOUT_MS` (default `2000` ms) | Transaction was rolled back cleanly; POS resends the exact same `transaction_id` safely via idempotency |
| `reset_demo_db.ps1` exits with `HTTP 409 JOB_RUNNING` on `forecast` | After `01:00` UTC+7, the middleware scheduler's startup catch-up starts the `forecast` job immediately while `reset_demo_db.ps1` also calls `POST /api/v1/admin/jobs/forecast/run` | Database reset and container restart already succeeded and `forecast` is running via catch-up; wait ~10 s and verify forecasts in Demo Console or re-run `scripts/demo/run_job.ps1 -Name forecast` |
