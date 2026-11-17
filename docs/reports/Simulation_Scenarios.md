# Simulation scenarios

## 7. Duplicate storm

Measured on 2026-11-17 on isolated `RTS_DB_DEMO` with seed 42 and API commit
`762bce6` (main `41ecb28` plus the recommendation job, scheduler disabled).
The simulator used six terminals and a 0.30 duplicate probability through
the real mutual-TLS gateway. The run sent 236 requests in 15.297 seconds.
All 180 original events were accepted, and all 56 deliberate replays
returned DUPLICATE. There were no rejected events or transport errors.

The ledger matched opening stock plus movements for all 27 store/SKU pairs.
For this run ID, the signed movement total of every transaction and SKU
matched its accepted item quantity. Each replay therefore left stock
unchanged.

With the container prepared in [Performance.md](Performance.md), run:

```bash
python prepare_performance.py duplicate-storm --duration-minutes 0.25 --run-id phase7-final-duplicate-storm --output /tmp/storm.yaml
python /repo/scripts/perf/reconcile_demo.py snapshot /tmp/storm-opening.json
time python -m pos_simulator --config /tmp/storm.yaml
python /repo/scripts/perf/reconcile_demo.py reconcile /tmp/storm-opening.json --run-id phase7-final-duplicate-storm
```
