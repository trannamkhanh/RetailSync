# Simulation scenarios

Live verification results for the DS-09 Section 7 simulation scenarios (`docs/design/DS-09_Test_Strategy_and_Simulator.md`). Each owner records their assigned scenarios (Scenarios 1–5: Kiet; Scenarios 6 and 8: Khanh; Scenario 7: Sang).

## 6. WAN outage between POS and Middleware (5 minutes)

- **Owner:** Khanh (DS-09 Section 7 row 6; DS-05 Section 8 & Section 10 #13)
- **Branch / Commit:** `docs/PB-42-1-deployment-guide` at commit `306e1e7` (base `main` `0bdea8d`; code unchanged from `main`)
- **Database:** `RTS_DB_DEMO` (middleware) and `RTS_HQ` (HQ demo, mode `ONLINE`)
- **Seed:** `42` (history seed `42` from `reset_demo_db.ps1`; simulator `seed: 42`, `run_id: ds09-s6-wan-outage`)
- **Business date:** `2026-11-19` (UTC+7)
- **Result:** **PASS** — POS-to-Middleware connectivity blocked for > 5 minutes (`2026-11-19T01:43:30Z` to `2026-11-19T01:51:26Z`; simulator actively blocked for 6 min 39 s from `01:44:47Z` to `01:51:26Z`, recording `107` connection errors); after restoration, all `30/30` planned events drained in strict chronological order per terminal with `0` lost events, `0` rejections, and `RECONCILIATION PASS`.

### Reproducible Setup and Commands

1. Reset `RTS_DB_DEMO` and `RTS_HQ` (with local loopback bind addresses if `.env` still holds a LAN IP):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
   ```

2. Save the simulator configuration as `tools/pos-simulator/config.s6.yaml` (not committed):
   ```yaml
   seed: 42
   run_id: ds09-s6-wan-outage
   start_at: '2026-11-19T02:00:00Z'
   event_count: 30
   base_url: https://pos-gateway:9443/api/v1
   stores:
     - store_id: STORE-DN1
       pos: [POS-DN1-01]
     - store_id: STORE-DN2
       pos: [POS-DN2-01]
   rate_per_pos_per_second: 0.1
   mix: {SALE: 0.92, RETURN: 0.05, CANCELLATION: 0.03}
   items_per_sale: {min: 1, max: 2}
   fault_injection:
     duplicate_rate: 0.02
     conflict_rate: 0.0
     timeout_retry_rate: 0.01
   catalogue:
     SKU-0001: '32000.00'
     SKU-0002: '7000.00'
     SKU-0003: '65000.00'
     SKU-0004: '25000.00'
     SKU-0005: '45000.00'
     SKU-0006: '38000.00'
     SKU-0007: '120000.00'
     SKU-0008: '4500.00'
     SKU-0009: '58000.00'
   ca_file: ../../.certs/ca.crt
   terminal_cert_dir: ../../.certs/pos
   tokens_file: ../../.tokens/demo_tokens.json
   summary_file: summary.s6.json
   request_timeout: 5
   max_attempts: 600
   ```

3. Block POS-to-Middleware connectivity by stopping `pos-gateway`, start the simulator while the WAN link is blocked, wait at least 5 minutes (300 s), then restore `pos-gateway`:
   ```powershell
   docker compose stop pos-gateway

   # In terminal 1:
   docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r requirements.txt && python -m pos_simulator --config config.s6.yaml'

   # After >= 5 minutes (300 s), in terminal 2:
   docker compose start pos-gateway
   ```

4. After the simulator exits, trigger a sync cycle and reconcile `RTS_DB_DEMO` against `RTS_HQ`:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/demo/sync_run.ps1
   docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ
   ```

### Observed Output

**Timeline (UTC):**
- `pos-gateway` stopped: `2026-11-19T01:43:30Z`
- Simulator started: `2026-11-19T01:44:47Z`
- `pos-gateway` restored: `2026-11-19T01:51:26Z` (total blocked interval while simulator active: **6 min 39 s**)
- Simulator completed: `2026-11-19T01:51:30Z` (all 30 events drained in ~4 s after link recovery)

**POS simulator summary:**
```json
{
  "connection_errors": 107,
  "duplicate": 2,
  "fault_conflict": 0,
  "fault_duplicate": 1,
  "fault_timeout_retry": 1,
  "latency_ms": {
    "p50": 4018.89,
    "p95": 8033.25,
    "p99": 8046.36
  },
  "ok": 30,
  "planned": 30,
  "rejected": {},
  "sent": 139,
  "service_unavailable": 0,
  "skipped_unaccepted_sale": 0,
  "timeouts": 0
}
```
*(Latency quantiles include the blocked `ConnectionError` retry attempts during the outage; `107 connection_errors + 30 ok + 2 duplicate = 139 sent`.)*

**Order and completeness check in `RTS_DB_DEMO` (`dbo.pos_transaction` ordered by `pos_id, created_at, txn_id`):**
```text
sim_txns=30
ORDER_CHECK POS-DN1-01: count=15 strict_order=True
ORDER_CHECK POS-DN2-01: count=15 strict_order=True
AUDITS: {'DUPLICATE_EVENT': 2, 'STOCK_CHANGE': 30, 'SYNC_ACKED': 2}
```
- `POS-DN1-01`: `SIM-11cb762004c2ca05-00000000` through `00000028` (15 `SALE` events, `2026-11-19 01:51:30.170` to `01:51:30.739`), strictly monotonic.
- `POS-DN2-01`: `SIM-11cb762004c2ca05-00000001` through `00000029` (14 `SALE` + 1 `RETURN` at index `00000023`, `2026-11-19 01:51:29.367` to `01:51:30.104`), strictly monotonic.

**Sync cycle (`scripts/demo/sync_run.ps1`):**
```text
POST https://localhost:8443/api/v1/sync/run as admin
HTTP 202   code: -   {"batches_created":2,"batches_sent":2,"batches_pending":0}
```

**Reconciliation (`scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ`):**
```text
Reconciling RTS_DB_DEMO with RTS_HQ
PASS 1 stock = opening + movements: 27 inventory rows
PASS 2 HQ totals = lines of ACKED batches: 2 ACKED batches, 18 store/SKU totals
PASS 3 each transaction in at most one batch: 2 batches, 30 linked transactions, 0 not batched yet
RECONCILIATION PASS
```

## 7. Duplicate storm

Measured on 2026-11-19 on isolated `RTS_DB_DEMO` and `RTS_HQ_TEST`.
The API and simulator application code match main
`abf26655ddfd7e2fc0503bfd579ded0db7750cde`. The scheduler was disabled.
Seed 42, six terminals and `duplicate_rate: 0.3` were used through the real
mTLS gateway with 50 ms egress netem delay.

Run ID `review60-20261119-duplicate-storm` sent **460 requests** in 31
whole wall-clock seconds for a scheduled 30-second sample. All **360
original events** were accepted, and all **100 exact resends** returned
DUPLICATE. There were zero rejections, HTTP 503s, transport errors or skipped
reversals. Request p50/p95/p99 were 166.23/199.34/286.11 ms.

The stock snapshot reconciliation after the run printed:

```text
Ledger balanced for 27 store/SKU pairs
```

The same check compared each transaction/SKU's signed movement total with
its accepted item quantity, including all batch movements. The 100 resends
therefore applied no extra stock changes.

The guide's `scripts/sync_reconcile.py` also ran immediately after the
storm. With scheduling disabled at that point, all 23,400 accepted events
from the baseline, sustained normal, peak and storm workloads were unbatched.
The script passed its stock check and reported zero ACKed batches.
To exercise its HQ checks against actual data, the isolated HQ service was
then started on `RTS_HQ_TEST` and an Admin `POST /api/v1/sync/run` returned:

```text
202 {"batches_created":3,"batches_sent":3,"batches_pending":0}
```

The final reconciliation output was:

```text
Reconciling RTS_DB_DEMO with RTS_HQ_TEST
PASS 1 stock = opening + movements: 27 inventory rows
PASS 2 HQ totals = lines of ACKED batches: 3 ACKED batches, 27 store/SKU totals
PASS 3 each transaction in at most one batch: 3 batches, 23400 linked transactions, 0 not batched yet
RECONCILIATION PASS
```

With the container prepared in [Performance.md](Performance.md), run:

```bash
python prepare_performance.py duplicate-storm --duration-minutes 0.5 --run-id review60-20261119-duplicate-storm --output /tmp/pb39-run/storm.yaml
python /repo/scripts/perf/reconcile_demo.py snapshot /tmp/pb39-run/storm-opening.json
time python -m pos_simulator --config /tmp/pb39-run/storm.yaml
python /repo/scripts/perf/reconcile_demo.py reconcile /tmp/pb39-run/storm-opening.json --run-id review60-20261119-duplicate-storm
python /repo/scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ_TEST --opening STORE-DN1=5040 --opening STORE-DN2=5025 --opening STORE-DN3=5015
```

The opening overrides account for the 5,000 units added per seeded
store/SKU before measurement. After all measured traffic ends, configure
the isolated HQ URL, CA and matching HQ JWT secrets, start HQ, and run
`POST /api/v1/sync/run` with an Admin token before repeating the final
reconciliation command. Reset the demo database after measurement to
restore seeded stock.

## 8. Stale snapshot during active sales

- **Owner:** Khanh (DS-09 Section 7 row 8; DS-05 Section 9 & Section 10 #12; PB-13 / NFR05)
- **Branch / Commit:** `docs/PB-42-1-deployment-guide` at commit `306e1e7` (base `main` `0bdea8d`; code unchanged from `main`)
- **Database:** `RTS_DB_DEMO` (middleware) and `RTS_HQ` (HQ demo, mode `ONLINE`)
- **Seed:** `4242` (history seed `42` from `reset_demo_db.ps1`; simulator `seed: 4242`, `run_id: ds09-s8-stale-snapshot`)
- **Business date:** `2026-11-19` (UTC+7)
- **Result:** **PASS** — `59/59` concurrent `POST /api/v1/hq/snapshot` calls returned HTTP `422 SNAPSHOT_REJECTED` and wrote `59` `SNAPSHOT_REJECTED` audit entries while `60/60` active POS events (`2` idempotent duplicates, `0` rejections) processed uninterrupted; `pb13_ledger_check.py` reported `LEDGER OK` (`0` mismatches) and `sync_reconcile.py` reported `RECONCILIATION PASS`.

### Reproducible Setup and Commands

1. Reset `RTS_DB_DEMO` and `RTS_HQ`:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
   ```

2. Save the simulator configuration as `tools/pos-simulator/config.s8.yaml` (not committed):
   ```yaml
   seed: 4242
   run_id: ds09-s8-stale-snapshot
   start_at: '2026-11-19T02:00:00Z'
   duration_minutes: 2
   base_url: https://pos-gateway:9443/api/v1
   stores:
     - store_id: STORE-DN1
       pos: [POS-DN1-01, POS-DN1-02]
   rate_per_pos_per_second: 0.25
   mix: {SALE: 0.92, RETURN: 0.05, CANCELLATION: 0.03}
   items_per_sale: {min: 1, max: 2}
   fault_injection:
     duplicate_rate: 0.02
     conflict_rate: 0.001
     timeout_retry_rate: 0.01
   catalogue:
     SKU-0001: '32000.00'
     SKU-0002: '7000.00'
     SKU-0003: '65000.00'
     SKU-0004: '25000.00'
     SKU-0005: '45000.00'
     SKU-0006: '38000.00'
     SKU-0007: '120000.00'
     SKU-0008: '4500.00'
     SKU-0009: '58000.00'
   ca_file: ../../.certs/ca.crt
   terminal_cert_dir: ../../.certs/pos
   tokens_file: ../../.tokens/demo_tokens.json
   summary_file: summary.s8.json
   request_timeout: 5
   max_attempts: 5
   ```

3. Run the POS simulator and the snapshot storm in parallel for 120 seconds:
   ```powershell
   # Terminal 1 (active sales over mTLS):
   docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONDONTWRITEBYTECODE=1 middleware sh -c 'pip install -q -r requirements.txt && python -m pos_simulator --config config.s8.yaml'

   # Terminal 2 (concurrent HQ snapshots every 2 s):
   docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo --env PYTHONDONTWRITEBYTECODE=1 middleware python scripts/demo/snapshot_during_sales.py --seconds 120 --interval 2.0 --url https://middleware:8443/api/v1/hq/snapshot
   ```

4. After both commands finish, trigger a sync cycle, run the ledger check, and reconcile:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/demo/sync_run.ps1
   docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python scripts/demo/pb13_ledger_check.py
   docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ
   ```

### Observed Output

**POS simulator summary (`2026-11-19T01:58:45Z` to `2026-11-19T02:00:41Z`):**
```json
{
  "connection_errors": 0,
  "duplicate": 2,
  "fault_conflict": 0,
  "fault_duplicate": 1,
  "fault_timeout_retry": 1,
  "latency_ms": {
    "p50": 72.24,
    "p95": 294.28,
    "p99": 347.07
  },
  "ok": 60,
  "planned": 60,
  "rejected": {},
  "sent": 62,
  "service_unavailable": 0,
  "skipped_unaccepted_sale": 0,
  "timeouts": 0
}
```

**Snapshot runner (`scripts/demo/snapshot_during_sales.py`):**
```text
snapshots sent=59 results={(422, 'SNAPSHOT_REJECTED'): 59}
```

**Sync cycle (`scripts/demo/sync_run.ps1`):**
```text
POST https://localhost:8443/api/v1/sync/run as admin
HTTP 202   code: -   {"batches_created":1,"batches_sent":1,"batches_pending":0}
```

**Ledger and batch-sum check (`scripts/demo/pb13_ledger_check.py`):**
```text
inventory rows=27 transactions=2380 snapshot_audits=59
mismatches: none
LEDGER OK
```
*(2,320 seeded `HIST-` rows + 60 live `SIM-` transactions = 2,380 transactions; every inventory row matches both `opening + SUM(inventory_movement)` and `SUM(product_batch.quantity)`.)*

**Reconciliation (`scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ`):**
```text
Reconciling RTS_DB_DEMO with RTS_HQ
PASS 1 stock = opening + movements: 27 inventory rows
PASS 2 HQ totals = lines of ACKED batches: 1 ACKED batches, 9 store/SKU totals
PASS 3 each transaction in at most one batch: 1 batches, 60 linked transactions, 0 not batched yet
RECONCILIATION PASS
```
