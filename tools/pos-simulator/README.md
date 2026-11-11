# POS event simulator

PB-03 generates a fixed POS event plan and sends it through the mTLS gateway.
Use a gateway connected to `RTS_DB_DEMO` for live demo checks. See the
[repository setup](../../README.md) for issuing and registering certificates
and tokens against that database.

From this directory on a Python 3.11+ host:

```powershell
python -m pip install -r requirements.txt
Copy-Item config.example.yaml config.local.yaml
python -m pos_simulator --config config.local.yaml
```

The example targets `https://localhost:9443/api/v1`. Paths to credentials and
the output file are relative to the YAML file. A fixed `seed`, `run_id`,
`start_at` and configuration produce the same plan and transaction IDs. Use a
fresh `run_id` for a new demo and keep it to replay an existing one. Specify
either `event_count` or `duration_minutes`. The mix contains relative weights,
and each terminal is paced independently.

The simulator skips planned reversals if their original sale did not receive
an OK or DUPLICATE response. Each terminal uses its own certificate and token.
Faults include exact duplicates, altered SALE resends, and a simulated lost
acknowledgement followed by an exact resend. A real timeout or 503 also
resends the original payload up to `max_attempts`.

The printed and saved JSON includes wire attempts, successful and duplicate
responses, rejections by code, skipped reversals, and p50/p95/p99 latency in
milliseconds. The latency sample includes retries and deliberate resends.

## Stock for longer demo runs

Use a disposable demo database. The reset script drops and recreates
`RTS_DB_DEMO`, including any simulated history already loaded into it. Set
`DB_NAME=RTS_DB_DEMO` in your local `.env`, then run from the repository root
in PowerShell:

```powershell
docker compose up -d --wait sqlserver
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1
docker compose up -d --force-recreate --wait middleware pos-gateway
```

The script restores the seeded stock and issues fresh demo tokens. Seeded
stock is limited even after a reset. For a long run, provision enough
sellable batches in the demo database before starting, or reduce the event
rate or count to fit the available stock. Use a fresh `run_id` for each
independent run. For a conflict demonstration, use a short run on freshly
seeded stock and raise `fault_injection.conflict_rate`. Conflict resends
require an accepted SALE, so a stock-depleted run can produce none.

## Container runs

For a live container run on the gateway's Compose network, set
`base_url: https://pos-gateway:9443/api/v1` in `config.local.yaml`. Run from
the repository root after starting the demo gateway:

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r requirements.txt && python -m pos_simulator --config config.local.yaml'
```

Run the network-free tests from the repository root:

```powershell
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONPATH=/repo/middleware:/repo/tools/pos-simulator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r requirements.txt -r /repo/middleware/requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```
