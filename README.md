# RetailSync

Regional middleware between POS terminals and HQ: realtime multi-store inventory, hourly aggregated sync, near-expiry alerts, forecasts and guardrail-validated recommendations. Capstone 1, team C1SE.24.

## Layout

| Path | Content |
|---|---|
| `middleware/` | FastAPI service; modules follow the Architecture module view |
| `database/` | Versioned SQL Server migrations, HQ mock tables, seed data |
| `docs/design/` | DS-04 OpenAPI contract, DS-05 sync design, DS-07 guardrail rules |
| `clients/demo-pos/` | WinForms demo POS with monitor panels (PB-45 part 1) |
| `clients/demo-console/` | WinForms demo console for the presenter on machine S (PB-42-6) |

Planned: `hq-demo/` (PB-18) and `staff-app/` (WinForms client, PB-46, PB-47).

## Run

Requires Docker Desktop and Python 3.12.

```bash
cp .env.example .env
docker compose up -d --wait sqlserver
docker compose run --rm migrate
bash scripts/generate_dev_certs.sh
docker compose up --build middleware
```

Docker health check: `https://localhost:8443/api/v1/health`

### HTTPS

The `middleware` service in Docker serves HTTPS only, on port 8443, with TLS 1.2
or higher. Native `uvicorn --reload` stays HTTP on port 8000 for local development.

`scripts/generate_dev_certs.sh` needs `openssl` and writes, in `.certs/`:

| File | Content |
|---|---|
| `ca.key`, `ca.crt` | Development CA |
| `server.key`, `server.crt` | Server certificate of `middleware`, `pos-gateway` and `hq-demo`, issued by the CA, valid for `localhost`, `127.0.0.1`, `middleware.retailsync.local`, `middleware`, `hq-demo` and `pos-gateway` |
| `pos/<pos_id>.key`, `pos/<pos_id>.crt` | Client certificate of each seeded terminal, common name `pos_id` (PB-48) |

Running it again keeps every valid certificate. A server certificate the CA did
not issue, such as the self-signed one from PB-02-1, is replaced once; set
`RENEW=1` to replace everything. Never commit `.certs/`.

Run it from Git Bash, which includes `openssl`. In PowerShell, plain `bash` may
start WSL instead, so name Git Bash:

```powershell
& "$env:ProgramFiles\Git\bin\bash.exe" scripts/generate_dev_certs.sh
```

Check the service against that certificate:

```powershell
curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://localhost:8443/api/v1/health
```

Windows `curl.exe` uses Schannel, which looks for revocation data the
development CA does not publish; `--ssl-no-revoke` skips that lookup.

`docker compose up middleware` needs the certificate and exits without it.
`docker compose run` for tests and migrations does not.

### POS gateway (mutual TLS, PB-48)

```text
POS ──(TLS 1.2+, client certificate, port 9443)──> pos-gateway (nginx) ──> middleware:8443
Staff, Admin, Auditor ──(TLS 1.2+, port 8443)──────────────────────────> middleware:8443
```

POS terminals send events only through `pos-gateway`. It requires a client
certificate issued by the development CA: without one, nginx completes the TLS
handshake and answers 400, so nothing reaches the middleware. It forwards only
`POST /api/v1/pos/events` (anything else gets 404), verifies the middleware's
certificate, and sets `X-Client-Cert` and `X-Gateway-Secret` on every request.

In Docker, `MTLS_REQUIRED=true`. The middleware then refuses a POS event with 403
`FORBIDDEN` when the gateway secret is missing or wrong, when no certificate was
forwarded, or when the certificate's fingerprint is not the one stored in
`pos_terminal.cert_fingerprint` for the event's `pos_id`. A POS event sent
straight to port 8443 is therefore refused. Native runs keep `MTLS_REQUIRED=false`.

`POS_BIND_ADDRESS` is the address `pos-gateway` publishes port 9443 on. It is the
private WAN interface of the regional server, and never a public address. The
default, `127.0.0.1`, keeps the gateway local to the machine.

Run once after pulling this change, from the repository root in PowerShell:

1. Add a gateway secret to `.env` (both `middleware` and `pos-gateway` read it):

   ```powershell
   $bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
   Add-Content .env ("POS_GATEWAY_SECRET=" + (-join ($bytes | ForEach-Object { $_.ToString('x2') })))
   ```

2. Regenerate the certificates. This adds the CA and the POS certificates and
   replaces the phase 2 server certificate:

   ```powershell
   & "$env:ProgramFiles\Git\bin\bash.exe" scripts/generate_dev_certs.sh
   ```

3. Store the POS certificate fingerprints in `RTS_DB`. It prints names and
   fingerprints, never keys. Run it again whenever a client certificate is reissued:

   ```powershell
   docker compose build middleware
   docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python scripts/register_pos_certificates.py
   ```

4. Start the middleware and the gateway:

   ```powershell
   docker compose up -d --wait middleware pos-gateway
   ```

Check TLS on port 9443 (TLS 1.2 and 1.3 connect, TLS 1.1 is refused):

```powershell
& "$env:ProgramFiles\Git\bin\bash.exe" scripts/check_pos_tls.sh
```

Check what the gateway forwards: paths with `..`, `.` or encoded characters are
refused, or reach the middleware as `/api/v1/pos/events`:

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo --entrypoint bash middleware scripts/check_pos_gateway.sh
```

#### Send a test event with a client certificate on Windows

Windows `curl.exe` uses Schannel, which does not send these client
certificates (with PEM or PKCS#12 files it fails before the request). Use
either of these from the repository root, after `scripts/issue_demo_tokens.py`
has written `.tokens/demo_tokens.json` and with a SALE body in `sale.json`.

Python, from the Windows host through port 9443 (standard library only). Tested
on Windows 11 with Python 3.11.9; Python 3.12 works the same:

```powershell
@'
import json, ssl, urllib.error, urllib.request

pos_id = "POS-DN1-01"
token = json.load(open(".tokens/demo_tokens.json"))[pos_id]
context = ssl.create_default_context(cafile=".certs/ca.crt")
context.load_cert_chain(f".certs/pos/{pos_id}.crt", f".certs/pos/{pos_id}.key")
request = urllib.request.Request(
    "https://localhost:9443/api/v1/pos/events", data=open("sale.json", "rb").read(), method="POST",
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(request, context=context) as response:
        print(response.status, response.read().decode())
except urllib.error.HTTPError as error:
    print(error.code, error.read().decode())
'@ | py -3.12 -
```

`curl` with OpenSSL, from the middleware image on the compose network. It still
checks the `localhost` server name. Also tested; put the token in `$token` first:

```powershell
$token = (Get-Content .tokens\demo_tokens.json -Raw | ConvertFrom-Json).'POS-DN1-01'
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo --entrypoint curl middleware --connect-to localhost:9443:pos-gateway:9443 --cacert .certs/ca.crt --cert .certs/pos/POS-DN1-01.crt --key .certs/pos/POS-DN1-01.key -H "Authorization: Bearer $token" -H "Content-Type: application/json" --data-binary "@sale.json" https://localhost:9443/api/v1/pos/events
```

Without a client certificate the gateway answers 400. With another terminal's
certificate, or sent straight to port 8443, the event gets 403 `FORBIDDEN`.

#### Database locks on the POS path (PB-04-5)

Each single wait for a database lock while a POS event is handled, from the
token's account lookup to the audit insert, lasts at most `POS_LOCK_TIMEOUT_MS`
(default 2000, positive values only). This is a limit per lock wait, not per
request: an event that meets several held locks can wait longer in total. When a
wait times out, the event is rolled back and the POS gets 503
`SERVICE_UNAVAILABLE`, and it resends the same `transaction_id`. Each timeout is
logged as one warning line containing `SQL 1222`, without a traceback.

### HQ demo service (PB-18)

`hq-demo/` is a separate FastAPI app that simulates HQ. It serves HTTPS on
`127.0.0.1:9000` with the same `.certs/server.crt` and keeps its data in the
`HQ_DB_NAME` database, `RTS_HQ` by default.

Add the shared service secret to `.env` once:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
Add-Content .env ("HQ_JWT_SECRET=" + (-join ($bytes | ForEach-Object { $_.ToString('x2') })))
```

The server certificate must carry `hq-demo` and `pos-gateway`, so run the
certificate script again after pulling this change: it reissues the certificate
when the SAN list changes. Restart `middleware`, `pos-gateway` and `hq-demo`
afterwards.

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm migrate
docker compose build hq-demo
docker compose up -d --wait hq-demo
curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://localhost:9000/api/v1/health
```

`migrate` creates `HQ_DB_NAME` and applies `database/hq/*.sql` there once each,
with the HQ database's own `schema_migration` table.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/health` | public |
| `POST` | `/api/v1/sync` | middleware service token: HS256 signed with `HQ_JWT_SECRET`, `sub: rts-middleware`, `role: MIDDLEWARE`, `exp` |
| `GET` | `/api/v1/demo/batches` | public; received batches and totals |
| `PUT` | `/api/v1/demo/mode` | public; `ONLINE`, `OFFLINE`, `ERROR`, `SLOW`, `DROP_ACK` |

`POST /api/v1/sync` answers 200 ACK (with `duplicate: true` for a repeated
`batch_id` with the same content), 409 NACK `CONFLICT` for the same id with other
content, 422 NACK `INVALID_BATCH` for a body outside DS-04, and 503/500 for the
`OFFLINE`/`ERROR` demo modes. The idempotency hash is the SHA-256 of the compact,
key-sorted batch message from DS-05 section 2: `net_revenue` as a string with two
decimals and `created_at` excluded. The middleware `batch_hash(message)` must use
the same form.

### Demo console and demo scripts (PB-42-6, PB-42-7)

`clients/demo-console/` is the presenter's window on machine S: live stock and
batches, transactions and audit, sync batches and HQ totals, near-expiry alerts and
forecasts, with buttons for sync, HQ modes, the snapshot and job runs. It reads
`.env`, `.certs/` and `.tokens/` at run time, runs only SELECT statements and
refuses `RTS_DB` and `RTS_DB_TEST`. See `clients/demo-console/README.md`.

`scripts/demo/reset_demo_db.ps1` rebuilds `RTS_DB_DEMO` and `RTS_HQ` with 90 days
of history and batches near expiry. The one-action scripts `sync_run.ps1`,
`hq_mode.ps1`, `hq_snapshot.ps1`, `run_job.ps1`, `set_threshold.ps1`,
`cross_store.ps1` and `audit_tail.ps1` in the same folder are the fallback when the
console fails. The runbook is `docs/demo/Sprint_3_Demo.md`.

## Test

```bash
cd middleware
pip install -r requirements-dev.txt
pytest
```

### HQ demo tests (PB-18)

The HQ demo tests run against `RTS_HQ_TEST`, never `RTS_HQ`:

```powershell
docker compose run --rm -e HQ_DB_NAME=RTS_HQ_TEST migrate
docker compose run --rm -e HQ_DB_NAME=RTS_HQ_TEST --volume "${PWD}/hq-demo:/app" --workdir /app hq-demo sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

## Working rules

- `main` only receives reviewed pull requests. Use one branch per task, for example `feat/PB-05-sale-event`.
- Implement the contract in `docs/design/openapi.yaml`; change the contract first when it must change.
- Migrations are forward-only: never edit one that has been applied, add a new file.
- Do not commit secrets, `.env`, `bin/`, or `obj/`.

## Phase 1 database setup on Windows (PB-01-1, PB-01-6)

Prerequisites: Git, Docker Desktop using Linux containers, Python 3.12 (64-bit),
and Microsoft's **ODBC Driver 18 for SQL Server** (64-bit) for native Python.
The middleware image installs its own Linux ODBC driver. A local SQL Server
installation and Visual Studio are not required for this phase.

In PowerShell, start in the repository root (for example `C:\dev\RetailSync`):

```powershell
Set-Location C:\dev\RetailSync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set `MSSQL_SA_PASSWORD` to a strong local password and `JWT_SECRET` to a long
random value. Never commit `.env`. Keep these database values for native Python:

```dotenv
DB_HOST=127.0.0.1
SQLSERVER_PORT=14333
DB_NAME=RTS_DB
TEST_DB_NAME=RTS_DB_TEST
```

Settings load the repository root `.env`, then a working-directory `.env` if
present. Process environment variables take precedence. The password has no
code default. Importing the health app requires no database or password.

Start SQL Server and apply the existing forward-only migrations:

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm migrate
docker compose run --rm migrate
```

The first run on a new database reports `Applying 001_core.sql`,
`Applying 002_batches_alerts_forecast.sql`, `Applying 003_recommendations.sql`,
then `Database is up to date`. The second run reports only the final message.
The runner also executes the idempotent store/POS seed on each run.

Verify the database without printing credentials:

```powershell
docker compose exec sqlserver bash -c '/opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "$MSSQL_SA_PASSWORD" -C -b -d RTS_DB -Q "SET NOCOUNT ON; SELECT COUNT(*) AS application_tables FROM sys.tables WHERE name <> ''schema_migration''; SELECT COUNT(*) AS migration_tables FROM sys.tables WHERE name = ''schema_migration''; SELECT COUNT(*) AS stores FROM dbo.store; SELECT COUNT(*) AS pos_terminals FROM dbo.pos_terminal; SELECT version FROM dbo.schema_migration ORDER BY version;"'
```

Expected on a fresh setup: 19 application tables, one migration table, three
stores, six terminals, and three recorded migration versions. HQ tables belong
to a separate future service and are not installed into `RTS_DB`.

Create the test database using the PowerShell equivalent of an inline
`DB_NAME=RTS_DB_TEST` assignment, restoring any previous setting afterward:

```powershell
$previousDbName = $env:DB_NAME
try {
    $env:DB_NAME = 'RTS_DB_TEST'
    docker compose run --rm migrate
    if ($LASTEXITCODE -ne 0) { throw 'Test database migration failed' }
} finally {
    if ($null -eq $previousDbName) { Remove-Item Env:DB_NAME -ErrorAction SilentlyContinue }
    else { $env:DB_NAME = $previousDbName }
}
```

Run FastAPI natively from `middleware/`:

```powershell
Set-Location C:\dev\RetailSync\middleware
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Alternatively, from the root, create the certificate (see HTTPS above), then run
`docker compose build middleware` followed by `docker compose up -d middleware`,
which serves HTTPS on port 8443. Compose overrides the database host to
`sqlserver` and its port to `1433`, and waits for database health. Apply migrations
first. The health endpoint does not prove database connectivity.

In a second PowerShell terminal:

```powershell
Invoke-RestMethod http://localhost:8000/api/v1/health
Set-Location C:\dev\RetailSync\middleware
.\.venv\Scripts\python.exe -m pytest -q
```

Expected health result: `status` is `ok`. Database tests use real SQL Server in
`TEST_DB_NAME`, which must end in `_TEST` and differ from `DB_NAME`. Each test
creates its own `TEST-` rows. `db_session` uses an outer transaction and
`join_transaction_mode="create_savepoint"`; even a session commit is rolled back
at teardown. `client` overrides `get_db` with that session. Tests fail with setup
instructions rather than skip if SQL Server is unavailable. Identity counters
can advance after rollback; tests must not assume sequential identity values.

For an entirely container-based test run, from the repository root. Mount the
whole repository: the tests read `database/seed` and `scripts`, which are
outside `middleware/`.

```powershell
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo/middleware --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

Integration contract: import `get_db`, `SessionLocal`, and `Base` from
`app.core.db`; import the eleven Sprint 2 models from `app.domain.models`.
Services/repositories receive a session and never commit. Routers explicitly
commit a successful request. `get_db` rolls back exceptions and always closes
the session; it never commits automatically. Migrations alone create tables.
The `inventory_movement.batch_id` mapping has no foreign key in migration 001;
migration 002 adds its FK to `product_batch`, whose model is out of scope.

Troubleshooting:

- `IM002` or “Can't open lib”: install 64-bit ODBC Driver 18 for native
  Python, or rebuild the middleware image.
- Login failure: check `.env`. Changing its password does not change the password
  of an existing SQL Server volume; keep the original value.
- Connection refused: check `docker compose ps`, `docker compose logs sqlserver`,
  and host port `14333`. Containers use host `sqlserver`, port `1433`.
- Missing table/database: migrate both databases. Tests never call `create_all`
  or silently fall back to SQLite.
- Port conflict: change `SQLSERVER_PORT` for native clients. The internal SQL
  Server port stays `1433`. Stop any existing API on 8000 before starting another.
- Health-only check without SQL Server: `python -m pytest tests/test_health.py`.

No endpoint, authentication, or business-flow behavior is added by this phase.

### Verification on 1 November 2026

The default `retailsync_sqlserver_data` volume already existed before this task;
SQL Server 2022 exited with a SQLPAL startup error when using it. It was preserved.
Verification instead uses the isolated project `retailsync-sang-phase1`, with a
new volume and the same Compose file and SQL Server 2022 image. On this machine,
add `-p retailsync-sang-phase1` after `docker compose` in the commands above.
Do not delete or downgrade an existing SQL Server volume to fix a startup error.

On the isolated instance, initial migrations and their second run succeeded.
Counts were 19 application tables, one `schema_migration` table, three stores,
and six POS terminals; all three migration timestamps were unchanged on rerun.
`RTS_DB_TEST` was created with the PowerShell command above. The ODBC middleware
image built successfully. Verification uses Python 3.12 inside that image;
native Windows Python/ODBC execution has not been verified.
The full suite passed: **20 passed, 1 warning** (Starlette/AnyIO deprecation).
It verifies all eleven model mappings against the migrated schema, commit
isolation, dependency override, and exception rollback. A deliberately unreachable
test host produced the expected explicit setup failure. The running container
returned `{"status":"ok"}` and `SessionLocal` queried `RTS_DB` successfully.
