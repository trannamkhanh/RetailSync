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
docker compose up --build middleware
```

Health check: `http://localhost:8000/api/v1/health`

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
