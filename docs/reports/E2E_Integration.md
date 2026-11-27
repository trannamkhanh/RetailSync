# End-to-end integration (PB-37)

Business date: 27/11/2026 (UTC+7). Base main: fb858b2, a descendant of a82b90c. Test branch: test/PB-37-e2e, in its own worktree.

## Acceptance-criterion mapping (PB-37-1)

Source: Product Backlog PB-37 in C1SE_24_RetailSync_Sprint_Backlog_v1.4.xlsx. The existing DS-09 report is docs/reports/Simulation_Scenarios.md.

| PB-37 requirement | DS-09 scenario and prior result | Current-main evidence |
|---|---|---|
| POS -> Inventory -> Sync -> HQ end-to-end flow | Scenario 1: 21,600/21,600 events, ACKED batches and reconciliation PASS | Automated mTLS chain below: SALE, partial RETURN, a separate SALE and CANCELLATION; stock checked after each; all four IDs ACKED; HQ sold/returned/net delta 5/3/64,000; reconciliation PASS |
| No lost or duplicated transaction in the main scenarios, including loss of HQ connectivity | Scenario 2: POS continued, nine batches stayed PENDING then ACKED oldest-first; scenarios 3-5 cover slow HQ, lost ACK and HQ errors; scenario 7 covers duplicate storm | Fresh three-cycle HQ outage below: 15 events continue while HQ is OFFLINE, nine batches PENDING, then ordered ACK and reconciliation |
| WAN outage between POS and Middleware: buffered events resent in order, without loss or duplication | Scenario 6: >5-minute outage, 30/30 events drained per-terminal in order, reconciliation PASS | Fresh 349.5-second gateway outage below: 30/30 originals, two expected duplicate replies, exact planned IDs and strict order for each terminal, reconciliation PASS |

This mapping reuses the already measured DS-09 scenarios 1-8 as requested by the reduced PB-37 scope. It does not claim that every older scenario was rerun here. The two required reruns are scenarios 2 and 6.

## Isolated setup

Private Compose project retailsync-sang-s4, a new SQL volume, no host ports. All application sources are main fb858b2; only the new checker runs from this branch. DB_NAME=RTS_DB_DEMO and HQ_DB_NAME=RTS_HQ_TEST. The development stack was never stopped. Scheduler disabled; manual POST /sync/run uses the real registered aggregation/send jobs.

The same private database was prepared for PB-44: migrations and seed, 90 days of history (seed 42), and a documented +20 units per seed store/SKU in inventory and its first batch. Stock reconciliation openings are STORE-DN1=60, STORE-DN2=45, STORE-DN3=35. Expiry and guardrail settings were staged for PB-44; SKU-0007 remains sellable and is used for outage traffic. This database must be reset before a normal demo.

The initial setup checks exposed missing private gateway/HQ secrets and incorrect local certificate mounts, which were corrected before measurements. These were local setup errors, not main code findings. A four-event setup probe had been applied before HQ authentication was configured; the checker's initial sync settled those events before taking its HQ baseline. Therefore the normal check's final reconciliation includes eight transactions in two batches, while its measured delta covers only its own four IDs.

## Automated chain (PB-37-2)

Run inside the middleware container with the whole repository, terminal certificates and current demo tokens mounted:

```sh
python scripts/e2e/e2e_check.py --db RTS_DB_DEMO --hq-db RTS_HQ_TEST \
  --opening STORE-DN1=60 --opening STORE-DN2=45 --opening STORE-DN3=35
```

For this isolated run the private token file was passed with --tokens /evidence/s4-demo-tokens.json. Default use is .tokens/demo_tokens.json. The checker refuses any middleware database other than RTS_DB_DEMO and requires DB_NAME to match before sending requests. It reuses sprint2_smoke.py's TLS/mTLS transport, preserving transaction IDs on transient 503 retries.

A cancellation cannot reference the partially returned sale: the chain therefore uses SALE A (3), RETURN A (1), SALE B (2), CANCELLATION B. Expected stock offsets are -3, -2, -4, -2. The HQ baseline is taken before these four requests; exact expected deltas are sold=5, returned=3, net revenue=64,000 VND.

Captured normal-run output:

```text
PASS POST https://middleware:8443/api/v1/sync/run: HTTP 202 
PASS GET https://hq-demo:9000/api/v1/demo/batches: HTTP 200 
PASS stock available: STORE-DN1/SKU-0001=58
PASS SALE through mTLS gateway: E2E-76cd0b04a008-A HTTP 200 OK
PASS stock after SALE: expected=55, actual=55
PASS RETURN through mTLS gateway: E2E-76cd0b04a008-R HTTP 200 OK
PASS stock after RETURN: expected=56, actual=56
PASS SALE through mTLS gateway: E2E-76cd0b04a008-B HTTP 200 OK
PASS stock after SALE: expected=54, actual=54
PASS CANCELLATION through mTLS gateway: E2E-76cd0b04a008-C HTTP 200 OK
PASS stock after CANCELLATION: expected=56, actual=56
PASS POST https://middleware:8443/api/v1/sync/run: HTTP 202 
PASS all four transactions ACKED: [('E2E-76cd0b04a008-A', 'SB-STORE-DN1-20261127091214', 'ACKED'), ('E2E-76cd0b04a008-B', 'SB-STORE-DN1-20261127091214', 'ACKED'), ('E2E-76cd0b04a008-C', 'SB-STORE-DN1-20261127091214', 'ACKED'), ('E2E-76cd0b04a008-R', 'SB-STORE-DN1-20261127091214', 'ACKED')]
PASS GET https://hq-demo:9000/api/v1/demo/batches: HTTP 200 
PASS ACKED batch present at HQ: ['SB-STORE-DN1-20261127091214']
PASS HQ totals match SALE/RETURN/CANCELLATION: sold/returned/net revenue delta=(5, 3, Decimal('64000.0'))
Reconciling RTS_DB_DEMO with RTS_HQ_TEST
PASS 1 stock = opening + movements: 27 inventory rows
PASS 2 HQ totals = lines of ACKED batches: 2 ACKED batches, 1 store/SKU totals
PASS 3 each transaction in at most one batch: 2 batches, 8 linked transactions, 0 not batched yet
RECONCILIATION PASS
PASS sync_reconcile: exit=0
E2E PASS
```

## Scenario 6: WAN outage (PB-37-4)

Stopped only retailsync-sang-s4-pos-gateway-1 at 09:12:48.162Z and restored it at 09:18:37.677Z on 27 Nov: **349.515 seconds (5 min 49.5 s)**. The simulator was started immediately after the stop and its setup completed within the first ten seconds, so active retry time exceeded five minutes.

Use a fresh run_id when repeating the measurement on a populated database. Configuration: seed 42; run_id sang-s4-wan-20261127; 30 events over POS-DN1-01 and POS-DN2-01; 0.1 events/s/terminal; default 92/5/3 mix; one SKU per sale, SKU-0007 at 120,000 VND; duplicate rate 0.02, timeout-resend 0.01; request timeout 2 s, max attempts 600. TLS CA and each terminal's certificate/key were used, with a reused requests session per terminal.

Commands (the normal compose form from DS-09 is equivalent; this private stack used the existing container name to avoid restarting migration dependencies):

```sh
docker stop retailsync-sang-s4-pos-gateway-1
cd /repo/tools/pos-simulator
python -m pos_simulator --config /evidence/s4-s6.yaml
# From the controlling terminal after >5 minutes:
docker start retailsync-sang-s4-pos-gateway-1
# After the simulator completed:
# POST /api/v1/sync/run as Admin
python scripts/sync_reconcile.py --db RTS_DB_DEMO --hq-db RTS_HQ_TEST \
  --opening STORE-DN1=60 --opening STORE-DN2=45 --opening STORE-DN3=35
```

Simulator output (retry-attempt latency includes the outage; these are not normal-load performance percentiles):

```json
{
  "connection_errors": 99,
  "duplicate": 2,
  "fault_conflict": 0,
  "fault_duplicate": 1,
  "fault_timeout_retry": 1,
  "latency_ms": {
    "p50": 3981.0,
    "p95": 8006.24,
    "p99": 8007.84
  },
  "ok": 30,
  "planned": 30,
  "rejected": {},
  "sent": 131,
  "service_unavailable": 0,
  "skipped_unaccepted_sale": 0,
  "timeouts": 0
}
```

The generated plan was loaded again using the same seed/run_id. Every planned ID was compared with committed pos_transaction rows ordered by terminal and created_at/txn_id, not just counted:

```text
ORDER_CHECK POS-DN1-01 count 15 strict_order True
ORDER_CHECK POS-DN2-01 count 15 strict_order True
PASS all 30 planned transaction IDs persisted exactly once in terminal order
POST /sync/run 202 {'batches_created': 2, 'batches_sent': 2, 'batches_pending': 0}
Reconciling RTS_DB_DEMO with RTS_HQ_TEST
PASS 1 stock = opening + movements: 27 inventory rows
PASS 2 HQ totals = lines of ACKED batches: 4 ACKED batches, 3 store/SKU totals
PASS 3 each transaction in at most one batch: 4 batches, 38 linked transactions, 0 not batched yet
RECONCILIATION PASS
```

## Scenario 2: HQ outage (PB-37-3)

HQ OFFLINE from 09:19:13.410Z until 09:22:13.410Z (180.01 seconds), covering three manual sync cycles 60 seconds apart. Every cycle sent five real mTLS events on SKU-0007 at 120,000 VND: DN1 SALE 2 / RETURN 1, DN2 SALE 2 / CANCELLATION of that sale, DN3 SALE 1. All 15 answered 200 while HQ stayed unavailable. Each cycle called POST /sync/run as Admin; the batches remained PENDING. The oldest batch accumulated three 503 HQ_OFFLINE attempts; all eight newer batches had zero attempts, proving the global send gate. After ONLINE, all nine ACKED and the order in GET /demo/batches exactly matched local created_at/batch-id order. All 15 planned IDs were present once.

Reproduction on the private stack: PUT /api/v1/demo/mode {"mode":"OFFLINE"}; send the five events per cycle through the terminal certificate gateway; POST /api/v1/sync/run at 0, 60 and 120 seconds; at 180 seconds PUT {"mode":"ONLINE"}; POST /sync/run until ACKED; compare HQ order and run sync_reconcile. The mode was restored in a finally block so an assertion failure could not leave HQ offline.

Captured output:

```text
HQ OFFLINE 2026-11-27T09:19:13.409665+00:00
CYCLE 1 accepted_events 5 {'batches_created': 3, 'batches_sent': 0, 'batches_pending': 3}
PENDING [('SB-STORE-DN1-20261127091913', 'PENDING', 1, '503 HQ_OFFLINE: HQ is offline for this demo.'), ('SB-STORE-DN2-20261127091913', 'PENDING', 0, None), ('SB-STORE-DN3-20261127091913', 'PENDING', 0, None)]
CYCLE 2 accepted_events 10 {'batches_created': 3, 'batches_sent': 0, 'batches_pending': 6}
PENDING [('SB-STORE-DN1-20261127091913', 'PENDING', 2, '503 HQ_OFFLINE: HQ is offline for this demo.'), ('SB-STORE-DN2-20261127091913', 'PENDING', 0, None), ('SB-STORE-DN3-20261127091913', 'PENDING', 0, None), ('SB-STORE-DN1-20261127092013', 'PENDING', 0, None), ('SB-STORE-DN2-20261127092013', 'PENDING', 0, None), ('SB-STORE-DN3-20261127092013', 'PENDING', 0, None)]
CYCLE 3 accepted_events 15 {'batches_created': 3, 'batches_sent': 0, 'batches_pending': 9}
PENDING [('SB-STORE-DN1-20261127091913', 'PENDING', 3, '503 HQ_OFFLINE: HQ is offline for this demo.'), ('SB-STORE-DN2-20261127091913', 'PENDING', 0, None), ('SB-STORE-DN3-20261127091913', 'PENDING', 0, None), ('SB-STORE-DN1-20261127092013', 'PENDING', 0, None), ('SB-STORE-DN2-20261127092013', 'PENDING', 0, None), ('SB-STORE-DN3-20261127092013', 'PENDING', 0, None), ('SB-STORE-DN1-20261127092113', 'PENDING', 0, None), ('SB-STORE-DN2-20261127092113', 'PENDING', 0, None), ('SB-STORE-DN3-20261127092113', 'PENDING', 0, None)]
HQ ONLINE 2026-11-27T09:22:13.410161+00:00 offline seconds 180.01
PASS 15/15 events persisted uniquely; 9/9 batches ACKED; oldest-first order matches HQ
LOCAL ORDER ['SB-STORE-DN1-20261127091913', 'SB-STORE-DN2-20261127091913', 'SB-STORE-DN3-20261127091913', 'SB-STORE-DN1-20261127092013', 'SB-STORE-DN2-20261127092013', 'SB-STORE-DN3-20261127092013', 'SB-STORE-DN1-20261127092113', 'SB-STORE-DN2-20261127092113', 'SB-STORE-DN3-20261127092113']
HQ ORDER ['SB-STORE-DN1-20261127091913', 'SB-STORE-DN2-20261127091913', 'SB-STORE-DN3-20261127091913', 'SB-STORE-DN1-20261127092013', 'SB-STORE-DN2-20261127092013', 'SB-STORE-DN3-20261127092013', 'SB-STORE-DN1-20261127092113', 'SB-STORE-DN2-20261127092113', 'SB-STORE-DN3-20261127092113']
Reconciling RTS_DB_DEMO with RTS_HQ_TEST
PASS 1 stock = opening + movements: 27 inventory rows
PASS 2 HQ totals = lines of ACKED batches: 13 ACKED batches, 4 store/SKU totals
PASS 3 each transaction in at most one batch: 13 batches, 53 linked transactions, 0 not batched yet
RECONCILIATION PASS
```

## Verification and findings (PB-37-5)

Pure-helper regression test test_pb37_stock_and_hq_delta_helpers covers expected stock offsets, exact Decimal HQ delta, absent totals, and duplicate total-row rejection. Full container suite: **1437 passed, 0 failed, 0 skipped, 0 xfail**. Command from the root, with RTS_DB_TEST and the entire repository mounted:

```sh
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/middleware \
  --env PYTHONDONTWRITEBYTECODE=1 --env TEST_DB_NAME=RTS_DB_TEST --env DB_NAME=RTS_DB_NOWRITE \
  middleware sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

Main independent retest evidence: middleware 1436, HQ 28, Staff App 84, Demo POS 116, Demo Console 165 passed; all zero skipped. No product finding was reproduced in the measured checks, so no product issue was invented. Local configuration corrections are documented above.

TC-SA: 87 assigned cases directly match passing named tests (including one report-method case with its own named regression), and evidence is retained in TC-SA_evidence.csv. The remaining 66 manual/report cases and shared-sheet edits need the exact workbook steps and access; TST37-7 remains excluded as assigned. No UAT sign-off, freeze/tag, merge, or another person's workbook results are claimed.
