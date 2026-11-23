# Simulation scenarios

Live verification results for the DS-09 Section 7 simulation scenarios (`docs/design/DS-09_Test_Strategy_and_Simulator.md`). Each owner records their assigned scenarios (Scenarios 1–5: Kiet; Scenarios 6 and 8: Khanh; Scenario 7: Sang).

## Scenarios 1 to 5: common setup (Kiet)

- **Owner:** Kiet (DS-09 Section 7 rows 1 to 5; DS-05 Section 10 #6, #7, #11)
- **Branch / Commit:** `feat/PB-40-sync-metrics` at `f5d82ee` (main `86245a7` plus `sync_batch.raw_bytes`); HQ demo image from `main`
- **Database:** `RTS_DB_DEMO` (middleware, not reset; stock replenished with `scripts/perf/replenish_demo.sql`, openings 5,040 / 5,025 / 5,015 per SKU) and `RTS_HQ_KIET` (temporary HQ database, created for the run and dropped after it)
- **Seed:** simulator `seed: 42`, `run_id: kiet-pb40-20261120-normal`
- **Business date:** `2026-11-20` (UTC+7); run from `02:27Z` to `03:27Z`
- **Stack:** an isolated stack on a private Docker network (the dev stack was not touched): middleware of the branch with `SCHEDULER_ENABLED=true`, `SYNC_INTERVAL=60`, `SYNC_RETRY_BASE_SECONDS=5`, `HQ_TIMEOUT_SECONDS=3`, `MTLS_REQUIRED=true`; the nginx POS gateway from `deploy/nginx/pos-gateway.conf.template`; `hq-demo` with `HQ_DB_NAME=RTS_HQ_KIET`. Every POS event went through the gateway with the terminal's certificate and token.
- **Reconciliation after each scenario:**
  ```bash
  python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ_KIET --opening STORE-DN1=5040 --opening STORE-DN2=5025 --opening STORE-DN3=5015
  ```
- **Scenarios 2 to 5:** for 3 sync cycles (3 minutes) HQ stays in the scenario's mode (`PUT /api/v1/demo/mode`) while each store sells once per cycle (DN1 a SALE and a RETURN, DN2 a SALE and its CANCELLATION, DN3 a SALE); then HQ goes back to `ONLINE` and the run waits until every batch is ACKED and no transaction is left unbatched. The order check compares the batches' creation order with the order in which HQ first received them (`GET /api/v1/demo/batches`).

Data reduction and success rate of these runs: [Sync_Metrics.md](Sync_Metrics.md).

## 1. Normal day

- **Result:** **PASS** -- 21,600 of 21,600 events OK (0 rejected, 1 `503` retried with the same id), 93 of 93 batches ACKED at the first attempt, `RECONCILIATION PASS`; data reduction 98.91 %.
- **Command** (in a container on the private network, repository at `/repo`):
  ```bash
  cd /repo/tools/pos-simulator
  python prepare_performance.py normal --run-id kiet-pb40-20261120-normal --output /tmp/run/normal.yaml
  python -m pos_simulator --config /tmp/run/normal.yaml
  ```
- **Simulator summary:** planned 21,600, ok 21,600, sent 21,601, service_unavailable 1, p50 124.91 ms, p95 239.25 ms, p99 382.56 ms, wall time 30 min 6 s (`02:38:50Z` to `03:08:56Z`).
- **Reconciliation:**
  ```text
  PASS 1 stock = opening + movements: 27 inventory rows
  PASS 2 HQ totals = lines of ACKED batches: 94 ACKED batches, 27 store/SKU totals
  PASS 3 each transaction in at most one batch: 94 batches, 21604 linked transactions, 0 not batched yet
  RECONCILIATION PASS
  ```
  (94 includes one batch of 4 older transactions from 12 Nov, aggregated when the stack started.)

## 2. HQ outage

- **Result:** **PASS** -- HQ `OFFLINE` from `03:10:18Z` to `03:13:21Z`: 15/15 events answered 200; 9 batches stayed PENDING; the oldest had 3 attempts with `503 HQ_OFFLINE` and backoff 5, 10, 20 s, the 8 newer ones waited untouched behind it (global send gate, DS-05 section 6). HQ back at `03:13:21Z`; all 9 ACKED by `03:14:01Z`, received oldest first; `RECONCILIATION PASS`.
- **Note:** scenario 2 adds 16 linked transactions (21,604 -> 21,620) while scenarios 3 to 5 add 15 each. The 16th is the probe sale `LIVE-PROBE-37c15c4b` (POS-DN3-01, `03:10:07Z`), sent once through the gateway to check the driver's client certificate before the scenario started; it joined `SB-STORE-DN3-20261120031057`.
- **Observed:**
  ```text
  SB-STORE-DN1-20261120031057  PENDING txns=2 attempts=3 retry_at=03:13:18 503 HQ_OFFLINE: HQ is offline for this demo.
  ... 8 newer batches PENDING, attempts=0
  ORDER OK (oldest first)
  PASS 1 stock = opening + movements: 27 inventory rows
  PASS 2 HQ totals = lines of ACKED batches: 103 ACKED batches, 27 store/SKU totals
  PASS 3 each transaction in at most one batch: 103 batches, 21620 linked transactions, 0 not batched yet
  RECONCILIATION PASS
  ```

## 3. Slow HQ

- **Result:** **PASS** -- HQ `SLOW` (4 s per call, client timeout 3 s) from `03:14:03Z` to `03:17:05Z`: 15/15 events answered 200; the oldest batch timed out 3 times (`No answer from HQ: ReadTimeout`) and was retried with backoff; HQ stored it during the slow calls, so the resend after `ONLINE` got `duplicate: true` and totals were not counted twice. All 9 batches ACKED by `03:17:59Z`, oldest first; `RECONCILIATION PASS`.
- **Observed:**
  ```text
  SB-STORE-DN1-20261120031457  PENDING txns=2 attempts=3 retry_at=03:17:21 No answer from HQ: ReadTimeout: The read operation timed out
  ORDER OK (oldest first)
  PASS 2 HQ totals = lines of ACKED batches: 112 ACKED batches, 27 store/SKU totals
  PASS 3 each transaction in at most one batch: 112 batches, 21635 linked transactions, 0 not batched yet
  RECONCILIATION PASS
  ```

## 4. Lost ACK

- **Result:** **PASS** -- HQ `DROP_ACK` from `03:18:02Z` to `03:21:04Z`: 15/15 events answered 200; HQ stored the oldest batch and answered `500 ACK_DROPPED` 3 times; the batch stayed PENDING with backoff. After `ONLINE` the resend was ACKED with `duplicate: true` (audit `SYNC_ACKED ... (duplicate)`), all 9 batches ACKED by `03:21:58Z`, oldest first, no double count; `RECONCILIATION PASS`.
- **Observed:**
  ```text
  SB-STORE-DN1-20261120031858  PENDING txns=2 attempts=3 retry_at=03:21:18 500 ACK_DROPPED: Batch stored, ACK dropped.
  ORDER OK (oldest first)
  PASS 2 HQ totals = lines of ACKED batches: 121 ACKED batches, 27 store/SKU totals
  PASS 3 each transaction in at most one batch: 121 batches, 21650 linked transactions, 0 not batched yet
  RECONCILIATION PASS
  ```

## 5. HQ errors

- **Result:** **PASS** -- HQ `ERROR` from `03:22:02Z` to `03:25:04Z`: 15/15 events answered 200; the oldest batch got `500 HQ_ERROR` 3 times and stayed PENDING with backoff, the others waited. All 9 ACKED by `03:25:58Z` after `ONLINE`, oldest first; `RECONCILIATION PASS`.
- **Observed:**
  ```text
  SB-STORE-DN1-20261120032258  PENDING txns=2 attempts=3 retry_at=03:25:18 500 HQ_ERROR: HQ failed for this demo.
  ORDER OK (oldest first)
  PASS 1 stock = opening + movements: 27 inventory rows
  PASS 2 HQ totals = lines of ACKED batches: 130 ACKED batches, 27 store/SKU totals
  PASS 3 each transaction in at most one batch: 130 batches, 21665 linked transactions, 0 not batched yet
  RECONCILIATION PASS
  ```
- **Across scenarios 1 to 5:** 130 `SYNC_ACKED` audits, 2 of them with `duplicate: true` (scenarios 3 and 4), no `SYNC_FAILED`.

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
   docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ
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
   docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ
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
