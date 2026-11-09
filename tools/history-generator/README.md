# Simulated sales history

PB-22-1 loads sales and a small number of returns into an existing, migrated
`RTS_DB_DEMO` or `RTS_DB_TEST`. It uses the catalogue and active terminals already
in the database. It marks the transactions `HIST-` and puts them in an ACKED
batch for each store. The generator leaves inventory, batches and movements alone.

From the repository root in PowerShell, with the demo database migrated and seeded:

```powershell
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo/tools/history-generator --env PYTHONPATH=/repo/middleware --env PYTHONDONTWRITEBYTECODE=1 middleware python -m history_generator --database RTS_DB_DEMO --days 90 --seed 42
```

The window ends before today's business date. Pass `--as-of YYYY-MM-DD` to pin
that date. The same catalogue, active terminals, date, days and seed reproduce
the same transaction data. A reload replaces the tool's history for those stores
in one transaction.

Run the SQL Server tests after migrating `RTS_DB_TEST`:

```powershell
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo/tools/history-generator --env PYTHONPATH=/repo/middleware:/repo/tools/history-generator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r /repo/middleware/requirements-dev.txt && python -m pytest -p no:cacheprovider -p tests.conftest -q tests'
```
