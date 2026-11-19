# Simulation scenarios

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
