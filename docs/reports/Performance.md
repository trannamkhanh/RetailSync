# PB-39 performance measurements

Measured on 2026-11-17 using Docker Desktop, SQL Server and `RTS_DB_DEMO` with
three seeded stores, six terminals and seed 42. The API ran at commit
`762bce6` (main `41ecb28` plus the recommendation job, with the scheduler
disabled). Each terminal used its own certificate and token through
`https://pos-gateway:9443/api/v1`. The simulator container used `NET_ADMIN` and
`tc qdisc add dev eth0 root netem delay 50ms`. The qdisc reported 50 ms on
egress, adding a nominal 50 ms to a round trip. This setup places all the
injected delay on one leg.

Before the measured runs, the demo stock helper added 5,000 units to each
of the 27 seeded store/SKU pairs in both inventory and a sellable batch.
Opening balances were captured separately before each run.

| Case | Target rate | Duration | Accepted / sent | p50 (ms) | p95 (ms) | p99 (ms) | Error rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| TST39-1 normal | 12/s | 30.276 s | 360 / 360 | 207.91 | 251.96 | 387.74 | 0% |
| TST39-2 peak | 36/s | 30.624 s | 1,080 / 1,080 | 160.40 | 208.02 | 259.33 | 0% |

Error rate counts terminal rejections, transport failures and HTTP 503
attempts relative to sends. All three counters were zero for these runs.
The observed normal-load POS p95 was below 500 ms. These are short samples.
The 30-minute DS-09 normal-load benchmark remains unverified.

- TST39-3 used a DN1 Staff token for 24 HTTPS lookups of barcode
  `8930000000011` during normal POS load. All returned HTTP 200. Lookup p95
  was 64.51 ms and the maximum was 234.08 ms.
- TST39-4 matched opening stock plus movement deltas for all 27 store/SKU
  pairs after both runs. Per-transaction/SKU signed movement totals also
  matched the accepted transaction items.

## Reproduce

Start the isolated demo stack using the [demo runbook](../demo/Sprint_2_Demo.md).
Apply `scripts/perf/replenish_demo.sql` with `sqlcmd -b -d RTS_DB_DEMO` before
taking the opening snapshot. The script expects sellable seeded batches and
uses the default UTC+7 business offset. Keep other demo traffic idle during
each run so opening stock and movements refer to the same workload.

From the repository root in PowerShell, start the simulator container:

```powershell
docker compose run --rm --no-deps --cap-add NET_ADMIN --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONPATH=/repo/middleware:/repo/tools/pos-simulator middleware bash
```

In the container, use a fresh run ID and output names for each measurement:

```bash
apt-get update -qq
apt-get install -y -qq iproute2
pip install -q -r requirements.txt
tc qdisc add dev eth0 root netem delay 50ms
tc qdisc show dev eth0
python prepare_performance.py normal --duration-minutes 0.5 --run-id phase7-final-normal --output /tmp/normal.yaml
python /repo/scripts/perf/reconcile_demo.py snapshot /tmp/normal-opening.json
python /repo/scripts/perf/measure_lookup.py &
lookup=$!
time python -m pos_simulator --config /tmp/normal.yaml
wait "$lookup"
python /repo/scripts/perf/reconcile_demo.py reconcile /tmp/normal-opening.json --run-id phase7-final-normal
```

Use the same steps with `peak` and run ID `phase7-final-peak` for the peak
sample. The normal scenario defaults to 30 minutes when no duration is
passed. Supply enough sellable demo stock for that duration.
