# Final report — technical part

**Author of this part:** Quang · **Lead editor:** Kiệt
**Base for the numbers:** draft on `a5f509b` (target snapshot: `v1.0`, frozen 30/11/2026) — re-check every figure on the freeze commit before submission.
**Scope:** architecture as built, data, tests, and measured results. Kiệt owns the surrounding narrative, the sprint narrative and the burn-down.

Every number below is taken from a committed file in `docs/reports/` or from a test run recorded in `docs/sprint-4/Regression_Evidence_v1.0.md`. Where a number is *not* available, this says so rather than estimating.

---

## 1. Architecture as built

Three tiers, as the design intended, with one difference worth stating: the middleware is a single database for the whole region, not one per store.

| Tier | What runs | What it stores |
|---|---|---|
| Store | Demo POS (WinForms), one per terminal; Staff App (WinForms) on machine A | **No business database.** Configuration, certificates, tokens, and an on-disk event queue for events that could not be sent during a WAN outage |
| Region | Middleware (FastAPI) behind an nginx POS gateway; scheduler runs the daily jobs | One database for the region: stock, batches, transactions, sync batches, alerts, forecasts, recommendations, audit. Every row carries `store_id` |
| HQ | HQ demo service (FastAPI) | Only per-store, per-SKU sales totals received from batches — not individual transactions |

**Transport and trust boundaries.**

- POS → middleware: port **9443**, nginx gateway, **TLS 1.2+**, **mTLS with a per-terminal client certificate**, plus a JWT with the POS role. The gateway refuses a request with no client certificate before the middleware sees it (`PS48-4`).
- Staff App and console → middleware: port **8443**, HTTPS, JWT by role.
- Middleware → HQ: port **9000**, HTTPS, JWT.
- SQL Server: port 14333, reachable only from S.
- No port is exposed to the internet. The POS and middleware bind addresses are explicit (`POS_BIND_ADDRESS`, `MIDDLEWARE_BIND_ADDRESS`), which is what makes the three-laptop private WAN demo work.

**Request path for a sale.** POS → gateway (mTLS + JWT) → middleware router → stock service → inventory and batch update in one transaction, with the movement row and the audit row written in the same transaction. Duplicate detection is by `transaction_id` plus a payload hash: same id and same content is `DUPLICATE_IGNORED`, same id and different content is `409 CONFLICT`.

**FEFO.** Sales consume the earliest-expiring sellable batch first; expired batches are skipped. Returns and cancellations restore the exact batch they took from (`EXP20-1`, `EXP20-5`, `EXP20-6`).

**Sync.** A scheduled aggregation turns each store's unsent transactions into one batch, sent to HQ oldest-first with ACK/NACK, backoff, and recovery of stale `SENT` batches at startup. HQ is idempotent by `batch_id`: a repeated batch is `ACK duplicate=true` and does not change totals.

**Intelligence.** Near-expiry alerts, a demand forecast (histogram gradient boosting with a seasonal-naive fallback), surplus/shortage, and recommendations that pass through a guardrail layer before a staff member ever sees them. Guardrails are per rule, and each check writes one result row.

**Layering rule that held across the codebase:** routers commit, services and repositories never commit. It is stated in all four briefs and enforced by review.

---

## 2. Data

| Store | Name | Role in the demo |
|---|---|---|
| `STORE-DN1` | Cửa hàng Hải Châu | POS-DN1-01, POS-DN1-02; staff account `staff_dn1` |
| `STORE-DN2` | Cửa hàng Thanh Khê | POS-DN2-01, POS-DN2-02; `staff_dn2` |
| `STORE-DN3` | Cửa hàng Sơn Trà | POS-DN3-01, POS-DN3-02; `staff_dn3` |

- **3 stores, 6 POS terminals, 9 SKUs.** Seed stock 40 / 25 / 15 per store/SKU. Partial indices on batches so FEFO stays index-friendly.
- **9 products in 3 categories** — `Dairy`, `Bakery`, `Dry goods` — with English names (`Fresh milk 1L`, `Bread 400g`, …). This is the seed as it stands on `main` and therefore the data every measurement was taken on.
- **90 days of simulated sales history** (`HIST-` transactions, never sent to HQ) to give the forecast a training window.
- Demo batches include near-expiry `Dairy` and `Bakery` lots so act 6 has real alerts and proposals.

`RTS_DB` (development) is never written by tests or measurements; tests use `RTS_DB_TEST` or a database whose name ends in `_TEST`, and the metrics scripts refuse `RTS_DB` outright.

---

## 3. Tests

All suites on `a5f509b`, full commands and output in `Regression_Evidence_v1.0.md`.

| Suite | Total | Failed | Skipped | xfail |
|---|---:|---:|---:|---:|
| Middleware (pytest) | 1459 | 0 | 0 | 0 |
| HQ demo (pytest) | 28 | 0 | 0 | 0 |
| `DemoConsole.Tests` | 165 | 0 | 0 | 0 |
| `DemoPos.Tests` | 116 | 0 | 0 | 0 |
| `StaffApp.Tests` | 84 | 0 | 0 | 0 |
| **Total** | **1852** | **0** | **0** | **0** |

Two facts a reader should not have to discover alone:

- The middleware run **must** mount the repository at `/repo`. Four tests read `database/seed` and `scripts/`; without the mount they **skip**, and a run with skips is not a green run. The 0-skipped above confirms the mount.
- `dotnet test` does not work on the demo host (VSTest testhost, `Win32Exception (5)`). The suites were executed with the xunit console runner. A committed runner exists for the demo console only; `DemoPos` and `StaffApp` were run with the same technique by hand. This is a **reproducibility gap** and is listed in §6.

**Test-case workbook.** 269 cases. The 27/11 export is **250 PASS, 19 Not Implemented, 0 FAIL**. Per sprint: Sprint 2 87/87, Sprint 3 87/87, Sprint 4 64/71 (7 not implemented), plus 24 cases (PB-49, PB-50) that map to no sprint because the backlog workbook has no Sprint 5 sheet.

---

## 4. Measured results

### 4.1 Performance (PB-39) — `docs/reports/Performance.md`

p95 POS API latency measured over the gateway with mTLS and 50 ms RTT, three stores, six terminals, own certificates and tokens, scheduler disabled to isolate POS traffic, demo database reset and replenished to 5,000 units per store/SKU.
**Target: under 500 ms.** Measured:

| Run | p50 | **p95** | p99 | Accepted / sent | Error rate |
|---|---:|---:|---:|---:|---:|
| Normal, sustained 30 min, 12/s | 186.94 ms | **226.60 ms** | 248.04 ms | 21,600 / 21,600 | 0% |
| Peak, 36/s | 159.51 ms | **193.51 ms** | 217.63 ms | 1,080 / 1,080 | 0% |
| Baseline, no netem, 12/s | 141.12 ms | **181.99 ms** | 478.27 ms | 360 / 360 | 0% |

Cross-store lookup (TST39-3), sampled once per second throughout the normal run: **1,805 responses, all HTTP 200, zero errors, p95 136.85 ms, maximum 206.56 ms.** Both p95 figures are inside the 500 ms target.

### 4.2 Sync and data reduction (PB-40) — `docs/reports/Sync_Metrics.md`

| Metric | Target | Measured |
|---|---|---|
| Data reduction to HQ, 30-minute normal run | ≥ 90% | **98.91%** |
| Data reduction, scenarios 1–5 | ≥ 90% | **98.77%** |
| Sync success rate | report | **100%** — 93/93 ACKED (scenario 1), 129/129 (scenarios 1–5) |

### 4.3 Forecast accuracy (PB-24) — `docs/reports/Forecast_Accuracy.md`

Holdout: 14 days from 2026-10-30, recursive prediction using only training demand and earlier predictions. Seed 42, simulated `HIST-` data.

`hgb-v1` beats `seasonal-naive-v1` in every category, for example Bakery MAE 3.05 vs 4.09 and WAPE 28.89% vs 38.75%. WAPE is undefined where total actual demand is zero, and the report marks those cells rather than printing a zero.

### 4.4 Near-expiry accuracy (PB-43) — `docs/reports/Near_Expiry_Accuracy.md`

Measured with `scripts/metrics/near_expiry_accuracy.py` against a labelled dataset where every batch has a known expected result: **100.0% correct — 32/32 batches, 0 missed, 0 false** across the three thresholds (3, 7, 14 days) and the default window, 8 batches each.

The report also carries an audit #11b re-run, because the earlier run had a config row present that suppressed the `NEAR_EXPIRY_DEFAULT_DAYS` fallback.

### 4.5 Guardrail and acceptance rates (PB-44) — `docs/reports/Guardrail_Metrics.md`

16 evaluated recommendations, business date 27/11:

| Outcome | Share |
|---|---|
| PASSED | 31.25% (5/16) |
| ADJUSTED | 31.25% (5/16) |
| BLOCKED | 37.50% (6/16) |

Per-rule-type rates use the worst result per recommendation/type, so denominators differ between rule types and are printed with each rate. Denominators below ten are marked **small sample** — which every per-store row here is. This is a staged sample, not UAT feedback, and the report says so.

**Staff acceptance rate** (`staff_decision` rows: ACCEPT / (ACCEPT + REJECT)):

| Population | ACCEPT | REJECT | Acceptance rate |
|---|---:|---:|---|
| All recommendations | 6 | 4 | **60.00% (6/10)** |
| DISCOUNT | 5 | 4 | 55.56% (5/9) — small sample |
| CLEARANCE | 1 | 0 | 100.00% (1/1) — small sample |
| REDISTRIBUTION | 0 | 0 | n/a |

Undecided rows: 0 PENDING and 0 EXPIRED without a decision. Six of ten decisions were ACCEPT — the scripted sample's mix, not an estimate of staff preference. Guardrail rates and acceptance rates use different populations and must not be compared as the same denominator.

### 4.6 End-to-end integration (PB-37) — `docs/reports/E2E_Integration.md`

Fresh evidence, not a re-quote of the simulator report:

- Automated mTLS chain POS → middleware → HQ: SALE, partial RETURN, separate SALE and CANCELLATION; stock checked after each; all four ACKED; HQ sold/returned/net delta 5/3/64,000; reconciliation PASS.
- HQ outage: 15 events processed while HQ offline, nine batches stayed PENDING, then ordered ACK and reconciliation PASS.
- Gateway outage: 349.5 seconds, 30/30 originals with two expected duplicate replies, exact planned ids and strict per-terminal order, reconciliation PASS.

---

## 5. What the numbers mean together

1. The store keeps operating through a WAN outage and an HQ outage, and reconciliation proves nothing was lost or double-counted. That is the claim the project set out to prove, and it is evidenced three ways (API-level, gateway-level, and the automated chain).
2. HQ receives ~1% of the transaction data and still reproduces the totals (98.91% reduction, 100% ACK). The savings are real, not an accounting artefact.
3. The forecast beats the seasonal-naive baseline in every category, so the recommendation layer is not built on a model that is worse than the trivial alternative.
4. Guardrails act on real proposals rather than being decorative: 5 of 16 were adjusted and 6 blocked.
5. Performance stays inside the 500 ms p95 target at the demo's terminal count.

---

## 6. Known limitations — state these, do not hide them

1. **Small samples in the guardrail metrics.** 16 recommendations, every per-store cell below 10. The percentages are illustrative of behaviour, not statistically meaningful, and the report marks them so.
2. **The metrics are staged, not UAT.** They were produced on a private stack with a known seed. They demonstrate the system can produce the numbers; they are not field measurements.
3. **Development CA.** Certificates come from a dev CA in `.certs/`, not a public one. mTLS is genuinely exercised; the trust anchor is not production-grade.
4. **No committed runner for two .NET suites.** `DemoPos.Tests` and `StaffApp.Tests` were run with the xunit console runner by hand. Until `run_client_tests.ps1` is committed, a third party cannot reproduce those two rows from the repository alone.
5. **PB-49 and PB-50 map to no sprint** in the backlog workbook. Report them as their own line; do not invent a Sprint 5 total.
6. **PB-44 workbook rows are still "Not Implemented"** even though the measurements exist. The report should not cite the workbook as evidence for PB-44 until Sang updates it.
7. **Demo console splitter (PB-41-8), deferred by decision.** When the console window is maximized after start, the stock panel keeps a small height; dragging the splitter by hand fixes it. This was to be fixed in PR Q1 and was deliberately deferred on 27/11 because the same app was being edited for PB-51. **Record it as a known limitation and drag the splitter before recording.**
8. **PB-51/52/53 are not on `main`.** The 27/11 brief describes Vietnamese-everywhere, a Dự báo tab with two charts, and a 30-product/six-category Vietnamese catalogue. None of it is in the repository at `a5f509b`; the evidence is in `UAT_Capstone_1_List.md` §11.1. If it merges before the freeze, this section changes and the affected measurements (forecast, recommendations, and therefore the guardrail sample) must be re-run on the new seed, because a different catalogue changes the demand data.
9. **The demo seed is 9 SKUs, not 30.** Every measurement above was taken on 9 SKUs in 3 categories. Changing the catalogue invalidates the comparison unless the jobs are re-run.

---

## 7. Artefacts to attach

| Artefact | Path |
|---|---|
| Performance | `docs/reports/Performance.md` |
| Sync metrics | `docs/reports/Sync_Metrics.md` |
| Forecast accuracy | `docs/reports/Forecast_Accuracy.md` |
| Near-expiry accuracy | `docs/reports/Near_Expiry_Accuracy.md` |
| Guardrail metrics | `docs/reports/Guardrail_Metrics.md` |
| E2E integration | `docs/reports/E2E_Integration.md` |
| Simulation scenarios | `docs/reports/Simulation_Scenarios.md` |
| Regression runbook and evidence | `docs/sprint-4/Regression_v1.0_Runbook.md`, `docs/sprint-4/Regression_Evidence_v1.0.md` |
| UAT list and bug list | `docs/sprint-4/UAT_Capstone_1_List.md`, `docs/sprint-4/Bug_List_PB-38-3.md` |
| Test-case review and re-test notes | `docs/sprint-4/Review_Test_Case_Sprint2-3.md`, `docs/sprint-4/Retest_Skipped_Cases.md`, `docs/sprint-4/Bao_Cao_Kiem_Thu_Sang_26-11.md` |
| Video plan | `docs/sprint-4/Video_Demo_Plan.md` — Kiet's Vietnamese plan of record (Phần A–D); the Dự báo tab in màn 6 is recorded only if PB-53 merges before the 12:00 30/11 freeze |
