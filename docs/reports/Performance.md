# PB-39 performance measurements

Measured on 2026-11-19 using Docker Desktop, SQL Server, `RTS_DB_DEMO`
and seed 42. The middleware, gateway configuration and simulator application
code match current main `abf26655ddfd7e2fc0503bfd579ded0db7750cde`.
The shared scheduler was disabled to isolate POS traffic. Three stores
used six terminals, each with its own certificate and token through
`https://pos-gateway:9443/api/v1`.

The disposable demo database was reset before measurement.
`scripts/perf/replenish_demo.sql` adds **5,000 units per store/SKU** to
`RTS_DB_DEMO`, updating both inventory and a sellable batch for each of
the 27 seeded pairs. This changed the openings to 5,040 units for DN1,
5,025 for DN2 and 5,015 for DN3. **Reset the demo database after measurement**
to restore the seeded quantities before later demonstrations.
After saving the results, the isolated demo database was reset. All nine
SKUs per store were verified at 40/25/15 units, and zero transactions remained.

## POS latency and errors

The baseline ran first in a fresh client container without netem. Before
the normal run, that container applied `tc qdisc add dev eth0 root netem
delay 50ms` with `NET_ADMIN`. The recorded qdisc showed `delay 50ms`.
This adds 50 ms of artificial TCP round-trip delay on the egress leg.
The peak and duplicate-storm runs retained the same qdisc.

| Case | Scheduled rate | Scheduled duration | CLI wall time | Accepted / sent | p50 (ms) | p95 (ms) | p99 (ms) | Error rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal baseline, no netem | 12/s | 30 s | 31 s | 360 / 360 | 141.12 | 181.99 | 478.27 | 0% |
| TST39-1 normal, 50 ms | 12/s | 30 min | 1,806 s | 21,600 / 21,600 | 186.94 | 226.60 | 248.04 | 0% |
| TST39-2 peak, 50 ms | 36/s | 30 s | 31 s | 1,080 / 1,080 | 159.51 | 193.51 | 217.63 | 0% |

CLI wall times were recorded in whole seconds and include plan generation,
TLS connection establishment and summary output. The normal scenario used
the default 30 minutes of `prepare_performance.py`. Its log starts at
08:11:39 UTC and finishes at 08:41:49 UTC, including setup and reconciliation.
All planned requests received OK, with zero HTTP 503s, transport failures,
rejections or skipped reversals. The normal p95 met the 500 ms target.

The original short samples had normal p50 207.91 ms and peak p50 160.40 ms.
The current normal baseline is 141.12 ms, and adding netem in the sustained
normal run increases p50 by 45.82 ms. This is consistent with the injected
50 ms RTT. A reused client session still includes gateway processing, the
gateway's HTTPS upstream connection and API/SQL work. The gateway uses its
default HTTP/1.0 upstream protocol, also visible in the API access logs.

The peak median remains 27.43 ms lower than the sustained normal median.
These sequential runs differ in sample size, run order, concurrency and
cache state. The measurements establish the observed latencies and the
baseline cost. They do not isolate the cause of the remaining difference.
Database group commits, connection setup and host scheduling would require
stage-level profiling to distinguish. The short peak sample is a limited
comparison with the 30-minute normal run.

## Cross-store lookup and reconciliation

TST39-3 sampled the DN1 Staff lookup once per second throughout the normal
POS run, continuing until the POS CLI completed. It collected **1,805
responses**, all HTTP 200, with **zero errors**, p95 **136.85 ms** and maximum
**206.56 ms**. The request used HTTPS on port 8443, the same client netem
qdisc, barcode `8930000000011` and `from_store=STORE-DN1`.

TST39-4 passed after the baseline, normal, peak and duplicate-storm runs.
For every run, stock equalled its opening snapshot plus movement deltas
across all 27 store/SKU pairs. Signed movements per transaction/SKU also
matched accepted item quantities. Scenario 7 includes the separate sync
reconciliation output in [Simulation_Scenarios.md](Simulation_Scenarios.md).

## Reproduce

Start a disposable demo stack using the [demo runbook](../demo/Sprint_2_Demo.md).
Reset `RTS_DB_DEMO` and an isolated HQ database before the run. Apply
`scripts/perf/replenish_demo.sql` with `sqlcmd -b -I -d RTS_DB_DEMO` once.
The script expects sellable seeded batches and the default UTC+7 offset.
Keep other demo traffic idle and the scheduler disabled during measurement.

From the repository root in PowerShell:

```powershell
docker compose run --rm --no-deps --cap-add NET_ADMIN --volume "${PWD}:/repo" --workdir /repo/tools/pos-simulator --env PYTHONPATH=/repo/middleware:/repo/tools/pos-simulator middleware bash
```

In that container, use a fresh directory and run IDs. Each summary is saved
beside its YAML file.

```bash
set -euo pipefail
apt-get update -qq
apt-get install -y -qq iproute2
pip install -q -r requirements.txt
mkdir /tmp/pb39-run
python prepare_performance.py normal --duration-minutes 0.5 --run-id review60-20261119-baseline --output /tmp/pb39-run/baseline.yaml
python /repo/scripts/perf/reconcile_demo.py snapshot /tmp/pb39-run/baseline-opening.json
time python -m pos_simulator --config /tmp/pb39-run/baseline.yaml
python /repo/scripts/perf/reconcile_demo.py reconcile /tmp/pb39-run/baseline-opening.json --run-id review60-20261119-baseline

tc qdisc add dev eth0 root netem delay 50ms
tc qdisc show dev eth0
python prepare_performance.py normal --run-id review60-20261119-normal --output /tmp/pb39-run/normal.yaml
python /repo/scripts/perf/reconcile_demo.py snapshot /tmp/pb39-run/normal-opening.json
python /repo/scripts/perf/measure_lookup.py --stop-file /tmp/pb39-run/lookup-stop > /tmp/pb39-run/lookup.json &
lookup=$!
time python -m pos_simulator --config /tmp/pb39-run/normal.yaml
touch /tmp/pb39-run/lookup-stop
wait "$lookup"
cat /tmp/pb39-run/lookup.json
python /repo/scripts/perf/reconcile_demo.py reconcile /tmp/pb39-run/normal-opening.json --run-id review60-20261119-normal

python prepare_performance.py peak --duration-minutes 0.5 --run-id review60-20261119-peak --output /tmp/pb39-run/peak.yaml
python /repo/scripts/perf/reconcile_demo.py snapshot /tmp/pb39-run/peak-opening.json
time python -m pos_simulator --config /tmp/pb39-run/peak.yaml
python /repo/scripts/perf/reconcile_demo.py reconcile /tmp/pb39-run/peak-opening.json --run-id review60-20261119-peak
```

Run scenario 7 next, then reset the disposable demo database and re-register
its certificate fingerprints using the demo reset procedure.
