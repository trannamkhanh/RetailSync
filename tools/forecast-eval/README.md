# Forecast accuracy evaluation

PB-24 compares HGB and seasonal naive by category on the last 14 days of
simulated sales history. Load 90 days into `RTS_DB_DEMO` first with the
[history generator](../history-generator/README.md).

From the repository root:

```powershell
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo --env PYTHONPATH=/repo/middleware:/repo/tools/forecast-eval --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r middleware/requirements-dev.txt && python -m forecast_eval && python -m pytest -p no:cacheprovider -q tools/forecast-eval/tests'
```

The tool reads only `HIST-` transactions and writes
`docs/reports/Forecast_Accuracy.md`. Pass `--as-of YYYY-MM-DD` to match the
exclusive end date used to seed history. Use `--output` for an alternate
output file.
