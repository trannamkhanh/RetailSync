# RetailSync

Regional middleware between POS terminals and HQ: realtime multi-store inventory, hourly aggregated sync, near-expiry alerts, forecasts and guardrail-validated recommendations. Capstone 1, team C1SE.24.

## Layout

| Path | Content |
|---|---|
| `middleware/` | FastAPI service; modules follow the Architecture module view |
| `database/` | Versioned SQL Server migrations, HQ mock tables, seed data |
| `docs/design/` | DS-04 OpenAPI contract, DS-05 sync design, DS-07 guardrail rules |

Planned: `hq-demo/` (PB-18), `pos-demo/` and `staff-app/` (WinForms clients, PB-45, PB-46, PB-47).

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

`bash scripts/generate_dev_certs.sh` needs `openssl` (Git Bash includes it). It
writes a self-signed certificate to `.certs/server.key` and `.certs/server.crt`,
valid for `localhost`, `127.0.0.1` and `middleware.retailsync.local`. Running it
again keeps a valid certificate; `RENEW=1 bash scripts/generate_dev_certs.sh`
replaces it. Never commit `.certs/`.

Check the service against that certificate:

```powershell
curl.exe --cacert .certs/server.crt https://localhost:8443/api/v1/health
```

`docker compose up middleware` needs the certificate. `docker compose run` for
tests and migrations does not.

## Test

```bash
cd middleware
pip install -r requirements-dev.txt
pytest
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

Alternatively, from the root, run `bash scripts/generate_dev_certs.sh`, then
`docker compose build middleware` followed by `docker compose up -d middleware`,
which serves HTTPS on port 8443 (see HTTPS above). Compose overrides the database host to
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
