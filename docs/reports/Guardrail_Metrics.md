# Guardrail and acceptance metrics (PB-44)

Business date: 27/11/2026 (UTC+7). Source code: main fb858b2 plus the PB-44 reporting script. Measured on Sang's private Compose project retailsync-sang-s4, with no published ports. Middleware database RTS_DB_DEMO; separate SQL volume. No writes targeted RTS_DB or the team's development stack.

## Method and reproduction

Run inside the middleware container with the whole repository mounted at /repo:

```sh
python scripts/metrics/guardrail_metrics.py --db RTS_DB_DEMO
```

The script is read-only and unconditionally refuses RTS_DB. All non-GENERATED recommendations are classified once: current BLOCKED status takes precedence, then any ADJUSTED rule result, otherwise PASSED. Rule-type rates count each recommendation once per type, taking its worst recorded result when several rules of that type apply. Rules skipped after an earlier block do not enter that rule type's denominator.

Acceptance is ACCEPT / (ACCEPT + REJECT) from staff_decision. Undecided PENDING and EXPIRED recommendations are reported separately. Each percentage includes numerator and denominator; denominators below ten are marked small sample; empty denominators display n/a.

This is a reproducible staged demo sample, not UAT/rehearsal feedback. After migrations and the seed, 90 days of history were generated with seed 42. The first batches of SKU-0001..0006 were moved to 0, 1, 3, 1, 2, 0 days until expiry respectively, in every store. The remaining first batches were moved to 60 days. MAX_DISCOUNT was set to 30 through the Admin API on this private stack to exercise adjustment. near-expiry, forecast and recommendation were run through /admin/jobs/{name}/run (all HTTP 200).

The initial seed left only three pending recommendations, so each was ACCEPTed through its store's Staff API. To obtain both decisions in several stores, 20 units per seed store/SKU were added to inventory and the first batch, then near-expiry and recommendation were rerun. Openings for later stock reconciliation are consequently STORE-DN1=60, STORE-DN2=45, STORE-DN3=35. All seven newly pending recommendations were alternately REJECTed and ACCEPTed through /recommendations/{id}/decision; all ten decisions returned HTTP 200. Reset this private DEMO database before using its stock or rule settings in a normal demonstration.

## Captured output

```text
Guardrail metrics for RTS_DB_DEMO; business date 2026-11-27 (UTC+7)

GENERATED excluded. Recommendation precedence: BLOCKED, then ADJUSTED, else PASSED.
Rule-type rates use the worst result per recommendation/type; denominators may differ.
Acceptance uses staff_decision only; undecided PENDING/EXPIRED rows are separate.

## Guardrail outcomes

| Store | Evaluated recommendations | PASSED | ADJUSTED | BLOCKED |
|---|---:|---:|---:|---:|
| STORE-DN1 | 5 | 20.00% (1/5) — small sample | 40.00% (2/5) — small sample | 40.00% (2/5) — small sample |
| STORE-DN2 | 6 | 50.00% (3/6) — small sample | 16.67% (1/6) — small sample | 33.33% (2/6) — small sample |
| STORE-DN3 | 5 | 20.00% (1/5) — small sample | 40.00% (2/5) — small sample | 40.00% (2/5) — small sample |
| TOTAL | 16 | 31.25% (5/16) | 31.25% (5/16) | 37.50% (6/16) |

## Outcomes per rule type

| Store / rule type | Recommendations checked | PASSED | ADJUSTED | BLOCKED |
|---|---:|---:|---:|---:|
| STORE-DN1 / MAX_DISCOUNT | 3 | 33.33% (1/3) — small sample | 66.67% (2/3) — small sample | 0.00% (0/3) — small sample |
| STORE-DN1 / MIN_PRICE | 3 | 100.00% (3/3) — small sample | 0.00% (0/3) — small sample | 0.00% (0/3) — small sample |
| STORE-DN1 / MIN_SHELF_LIFE | 5 | 60.00% (3/5) — small sample | 0.00% (0/5) — small sample | 40.00% (2/5) — small sample |
| STORE-DN2 / MAX_DISCOUNT | 3 | 66.67% (2/3) — small sample | 33.33% (1/3) — small sample | 0.00% (0/3) — small sample |
| STORE-DN2 / MIN_PRICE | 3 | 100.00% (3/3) — small sample | 0.00% (0/3) — small sample | 0.00% (0/3) — small sample |
| STORE-DN2 / MIN_SHELF_LIFE | 6 | 66.67% (4/6) — small sample | 0.00% (0/6) — small sample | 33.33% (2/6) — small sample |
| STORE-DN3 / MAX_DISCOUNT | 3 | 33.33% (1/3) — small sample | 66.67% (2/3) — small sample | 0.00% (0/3) — small sample |
| STORE-DN3 / MIN_PRICE | 3 | 100.00% (3/3) — small sample | 0.00% (0/3) — small sample | 0.00% (0/3) — small sample |
| STORE-DN3 / MIN_SHELF_LIFE | 5 | 60.00% (3/5) — small sample | 0.00% (0/5) — small sample | 40.00% (2/5) — small sample |
| TOTAL / MAX_DISCOUNT | 9 | 44.44% (4/9) — small sample | 55.56% (5/9) — small sample | 0.00% (0/9) — small sample |
| TOTAL / MIN_PRICE | 9 | 100.00% (9/9) — small sample | 0.00% (0/9) — small sample | 0.00% (0/9) — small sample |
| TOTAL / MIN_SHELF_LIFE | 16 | 62.50% (10/16) | 0.00% (0/16) | 37.50% (6/16) |

## Staff acceptance

| Store | ACCEPT | REJECT | Acceptance rate | PENDING without decision | EXPIRED without decision |
|---|---:|---:|---:|---:|---:|
| STORE-DN1 | 2 | 1 | 66.67% (2/3) — small sample | 0 | 0 |
| STORE-DN2 | 2 | 2 | 50.00% (2/4) — small sample | 0 | 0 |
| STORE-DN3 | 2 | 1 | 66.67% (2/3) — small sample | 0 | 0 |
| TOTAL | 6 | 4 | 60.00% (6/10) | 0 | 0 |

## Acceptance per action type

| Store / action | ACCEPT | REJECT | Acceptance rate | PENDING without decision | EXPIRED without decision |
|---|---:|---:|---:|---:|---:|
| STORE-DN1 / DISCOUNT | 2 | 1 | 66.67% (2/3) — small sample | 0 | 0 |
| STORE-DN1 / CLEARANCE | 0 | 0 | n/a (0/0) — small sample | 0 | 0 |
| STORE-DN1 / REDISTRIBUTION | 0 | 0 | n/a (0/0) — small sample | 0 | 0 |
| STORE-DN2 / DISCOUNT | 1 | 2 | 33.33% (1/3) — small sample | 0 | 0 |
| STORE-DN2 / CLEARANCE | 1 | 0 | 100.00% (1/1) — small sample | 0 | 0 |
| STORE-DN2 / REDISTRIBUTION | 0 | 0 | n/a (0/0) — small sample | 0 | 0 |
| STORE-DN3 / DISCOUNT | 2 | 1 | 66.67% (2/3) — small sample | 0 | 0 |
| STORE-DN3 / CLEARANCE | 0 | 0 | n/a (0/0) — small sample | 0 | 0 |
| STORE-DN3 / REDISTRIBUTION | 0 | 0 | n/a (0/0) — small sample | 0 | 0 |
| TOTAL / DISCOUNT | 5 | 4 | 55.56% (5/9) — small sample | 0 | 0 |
| TOTAL / CLEARANCE | 1 | 0 | 100.00% (1/1) — small sample | 0 | 0 |
| TOTAL / REDISTRIBUTION | 0 | 0 | n/a (0/0) — small sample | 0 | 0 |
```

## Reading

Six of sixteen recommendations were blocked (37.50%); five were adjusted (31.25%). Every block is associated with MIN_SHELF_LIFE. Five of nine MAX_DISCOUNT checks adjusted a proposal. Only nine MIN_PRICE checks ran because earlier blocks short-circuited rule evaluation.

Six of ten decisions were ACCEPT (60%). This is the scripted sample's mix, not an estimate of staff preference. Each store has only three or four decisions. DISCOUNT has nine decisions; CLEARANCE only one; REDISTRIBUTION has none, so its acceptance rate is n/a. Guardrail rates and acceptance rates use different populations and should not be compared as the same denominator.

## Verification

Nine test_pb44_* SQL-backed/CLI/pure cases cover outcome precedence, duplicate results of the same rule type, zero-percent BLOCKED, GENERATED exclusion, decision-only acceptance, undecided PENDING/EXPIRED, n/a, sample boundaries, database-name refusal, two-store TOTAL counts, and report headers. Full-container result is recorded in the PR description after the final run. The Google Sheet PB-44 entries remain pending access to the shared workbook; they have not been silently marked PASS.
