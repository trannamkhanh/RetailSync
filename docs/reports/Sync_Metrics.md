# PB-40 sync and data metrics

Measured on 2026-11-20 between 02:27 and 03:27 UTC (business date 2026-11-20, UTC+7) on `RTS_DB_DEMO`
with a temporary HQ database `RTS_HQ_KIET` (dropped after the run). Code: branch
`feat/PB-40-sync-metrics` at `f5d82ee` (main `86245a7` plus `raw_bytes`); the HQ demo is the `main`
image. Simulator seed 42, run id `kiet-pb40-20261120-normal`.

**Result:** TST40-1 data reduction **98.91 %** for the 30-minute normal run (target at least 90 %:
PASS) and **98.77 %** over scenarios 1 to 5. TST40-2 sync success rate **100 %** (93 of 93 batches
ACKED in scenario 1; 129 of 129 over scenarios 1 to 5, every batch of an HQ outage ACKED after HQ came
back).

## Definitions

- **`raw_bytes`** (filled by aggregation since this PR, TST40-3): the sum, over every transaction of
  the batch (SALE, RETURN and CANCELLATION), of the UTF-8 byte length of
  `json.dumps(event, separators=(",", ":"))`, where `event` is the DS-04 POS event rebuilt from the
  stored transaction: `event_type`, `transaction_id`, `store_id`, `pos_id`, `timestamp` (ISO 8601 UTC,
  seconds, `Z`), `items` with `sku`, `quantity` and `unit_price`, plus `original_transaction_id` for
  RETURN and CANCELLATION only; a CANCELLATION carries no items on the wire. `unit_price` is
  normalised to a two-decimal string, as the POS simulator sends it; DS-04 types it as a number and
  the demo POS sends a number, which is 2 bytes shorter per item, so the reduction would differ by
  well under 0.1 point. See `middleware/app/services/aggregation.py`.
- **`payload_bytes`**: the UTF-8 length of the batch message the sender posts to HQ
  (`len(payload)` in `app/integration/hq_client.py`), so both sizes are measured the same way.
- **Data reduction** = `1 - Σ payload_bytes / Σ raw_bytes` over ACKED batches.
- **Sync success rate** = ACKED batches / all batches.
- `SB-HIST-` history batches are excluded: they never go to HQ. Only batches created after the run
  started are counted (`--since 2026-11-20T02:36:32`), so the older batch of 4 transactions left from
  12 Nov (`SB-STORE-DN1-20261120022837`) is not in the figures.

## Setup

An isolated stack on a private Docker network, never the dev stack: the middleware of this branch
(TLS on 8443, `SCHEDULER_ENABLED=true`, `SYNC_INTERVAL=60`, `SYNC_RETRY_BASE_SECONDS=5`,
`HQ_TIMEOUT_SECONDS=3`, `MTLS_REQUIRED=true`), the nginx POS gateway from
`deploy/nginx/pos-gateway.conf.template`, and the `hq-demo` image with `HQ_DB_NAME=RTS_HQ_KIET`.
`RTS_DB_DEMO` was not reset; its stock was replenished with `scripts/perf/replenish_demo.sql` (5,000
units per store and SKU, as in PB-39), so the reconciliation openings are 5,040 / 5,025 / 5,015 per SKU
for STORE-DN1 / DN2 / DN3.

Scenario 1 is the PB-39 normal profile: `tools/pos-simulator/prepare_performance.py normal` (three
stores, six terminals with their own certificate and token, 2 events per second per terminal, 30
minutes) through the gateway. Scenarios 2 to 5 follow in
[Simulation_Scenarios.md](Simulation_Scenarios.md).

## Scenario 1: 30-minute normal load, HQ online

Simulator: 21,600 planned, 21,600 OK, 0 rejected, 1 `503` retried with the same id, p50 124.91 ms, p95
239.25 ms, p99 382.56 ms, wall time 30 min 6 s.

| Store | Batches | ACKED | FAILED | PENDING/SENT | Success rate | Σ payload_bytes | Σ raw_bytes | Data reduction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| STORE-DN1 | 31 | 31 | 0 | 0 | 100.00 % | 25,293 | 2,333,272 | 98.92 % |
| STORE-DN2 | 31 | 31 | 0 | 0 | 100.00 % | 25,378 | 2,322,291 | 98.91 % |
| STORE-DN3 | 31 | 31 | 0 | 0 | 100.00 % | 25,385 | 2,319,068 | 98.91 % |
| **Total** | **93** | **93** | 0 | 0 | **100.00 %** | **76,056** | **6,974,631** | **98.91 %** |

A one-minute batch carries about 230 transactions per store, so one summary message of about 820 bytes
replaces about 75 KB of single POS events.

## Scenarios 1 to 5 together

| Store | Batches | ACKED | FAILED | PENDING/SENT | Success rate | Σ payload_bytes | Σ raw_bytes | Data reduction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| STORE-DN1 | 43 | 43 | 0 | 0 | 100.00 % | 28,605 | 2,339,500 | 98.78 % |
| STORE-DN2 | 43 | 43 | 0 | 0 | 100.00 % | 28,594 | 2,327,943 | 98.77 % |
| STORE-DN3 | 43 | 43 | 0 | 0 | 100.00 % | 28,769 | 2,322,418 | 98.76 % |
| **Total** | **129** | **129** | 0 | 0 | **100.00 %** | **85,968** | **6,989,861** | **98.77 %** |

125 batches were ACKED at the first attempt. The oldest batch of each outage (scenarios 2 to 5) needed
3 failed attempts first (`503 HQ_OFFLINE`, `ReadTimeout`, `500 ACK_DROPPED`, `500 HQ_ERROR`); the
global send gate held the 8 newer batches of each outage back, untouched, and sent them oldest first
once HQ answered. The outage batches hold 1 to 2 transactions each, so they lower the total reduction
slightly; at the production `SYNC_INTERVAL` of 3600 seconds a batch holds far more transactions and the
reduction is higher still.

## Reproduce

Start the isolated stack (the names below are examples; the dev stack keeps running untouched):

```bash
docker network create rts-kiet
docker network connect --alias sqlserver rts-kiet retailsync-sqlserver-1
```

Create the temporary HQ database and its tables (`database/hq/001_hq_tables.sql`), start `hq-demo`
with `HQ_DB_NAME=RTS_HQ_KIET`, the middleware image of this branch with `DB_NAME=RTS_DB_DEMO` and the
settings above, and the gateway with the template, all on `rts-kiet` with the aliases `hq-demo`,
`middleware` and `pos-gateway`. Then, from the repository root:

```bash
sqlcmd -b -I -d RTS_DB_DEMO -i scripts/perf/replenish_demo.sql
```

In a container on `rts-kiet` with the repository mounted at `/repo`:

```bash
cd /repo/tools/pos-simulator
python prepare_performance.py normal --run-id kiet-pb40-20261120-normal --output /tmp/run/normal.yaml
python -m pos_simulator --config /tmp/run/normal.yaml
python /repo/scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ_KIET --opening STORE-DN1=5040 --opening STORE-DN2=5025 --opening STORE-DN3=5015
python /repo/scripts/metrics/sync_metrics.py --db RTS_DB_DEMO --since 2026-11-20T02:36:32
```

After the run, remove the containers and the network and drop `RTS_HQ_KIET`.

## Notes

- `RTS_DB_DEMO` keeps the replenished stock and the 21,665 transactions of this run until the next
  reset.
- The certificates in the main checkout's `.certs` were mixed on 20 Nov (`ca.crt` and `pos/` from
  another CA than `server.crt`), so TLS to the server failed. This run used the consistent set from
  11 Nov, whose POS fingerprints match `RTS_DB_DEMO`.
