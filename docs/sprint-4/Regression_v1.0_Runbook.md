# PB-41-10 regression on the frozen `main`

**Owner:** Quang · **When:** 30/11, after 12:00 (post-freeze) · **Recorded in:** the GitHub issue "Regression v1.0"
**Base:** the commit tagged `v1.0` (never a later commit)

This runbook is the one that was actually executed on 27/11 against `a5f509b`, so every command below is proven to work on this host. The numbers in §6 are that run's results and are the baseline the frozen run must match or explain.

---

## 0. Two facts that break a naive run

Fix these first or the run will report hundreds of false failures.

1. **`RTS_DB_TEST` can be a migration behind `RTS_DB`.** On 27/11 the suite failed with **221 failed, 32 errors**, all `Invalid column name 'occurred_at'` — the test database had not received `004_pos_transaction_occurred_at.sql`. Migrating it fixed every one of them with no code change. Always run the migration step below, and if a mass failure appears, check for a missing column before believing it is a regression.
2. **`dotnet test` does not work on this host.** The VSTest testhost aborts with `Win32Exception (5): Access is denied` before running a single test. Use the xunit console runner. `scripts/demo/run_console_tests.ps1` covers the demo console only; the demo-pos and staff-app suites need the same treatment (see §5). `scripts/demo/run_client_tests.ps1` is referenced by the 26/11 notes but is **not committed** — do not plan on it.

---

## 1. Prepare (before the run)

```powershell
cd <worktree of the v1.0 commit>
Copy-Item <your main checkout>\.env .env     # .env is never committed
```

`.env` must have `DB_NAME=RTS_DB_DEMO`, `TEST_DB_NAME=RTS_DB_TEST`, `MSSQL_SA_PASSWORD`, `JWT_SECRET`, `POS_GATEWAY_SECRET`.

Confirm the stack:

```powershell
docker compose ps
```

Expected services: `sqlserver`, `migrate` (exits 0), `middleware`, `hq-demo`, `pos-gateway`.

---

## 2. Migrate both test databases

This is step 0 of the run, not optional.

```powershell
# both test databases in one call: DB_NAME must travel with HQ_DB_NAME.
# Without -e DB_NAME the migration falls back to the .env value and would run
# against RTS_DB / RTS_DB_DEMO instead of RTS_DB_TEST.
docker compose run --rm -e DB_NAME=RTS_DB_TEST -e HQ_DB_NAME=RTS_HQ_TEST migrate
```

`--no-deps` may be added once `sqlserver` is healthy (`docker compose up -d --wait sqlserver` first); without that guard the migration would try to start the server itself.

Expected tail: `Database is up to date` and `HQ database RTS_HQ_TEST is up to date`. If either prints `Applying …`, it was behind — re-run it once to confirm it is now idle.

---

## 3. Middleware suite

`TEST_DB_NAME` must differ from `DB_NAME` and end in `_TEST`; the suite refuses to run otherwise.

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/middleware `
  --env PYTHONDONTWRITEBYTECODE=1 --env TEST_DB_NAME=RTS_DB_TEST --env DB_NAME=RTS_DB_NOWRITE `
  middleware sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

The `--volume "${PWD}:/repo"` is required: four tests read `database/seed` and `scripts/`, which sit outside `middleware/`, and are **skipped** without it. A run showing skips is not a valid regression run.

**Result on 27/11 (`a5f509b`):** `1459 passed, 2 warnings in 149.96s` — 0 failed, 0 skipped, 0 xfail.

---

## 4. HQ demo suite

```powershell
docker compose run --rm --no-deps -e HQ_DB_NAME=RTS_HQ_TEST --volume "${PWD}/hq-demo:/app" --workdir /app `
  hq-demo sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

**Result on 27/11:** `28 passed, 1 warning in 9.54s`.

---

## 5. The three .NET suites

The demo console has a committed runner. Use it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_console_tests.ps1
```

**Result on 27/11:** `DemoConsole.Tests Total: 165, Errors: 0, Failed: 0, Skipped: 0`.

`DemoPos.Tests` and `StaffApp.Tests` have **no committed runner**. Two routes:

- `scripts/demo/run_client_tests.ps1` does **not** exist in the repository, so unless someone commits it before the freeze, take the second route.
- Run the xunit console runner directly against the built assemblies, exactly as `run_console_tests.ps1` does (build, drop `xunit.console` into the test bin, write `xunit.console.runtimeconfig.json` for `Microsoft.WindowsDesktop.App`, copy the RID-specific `Microsoft.Data.SqlClient.dll` and `SNI.dll`, then run). The throwaway script used for the 27/11 run did this and is reproduced in `Regression_Evidence_v1.0.md`.

**Results on 27/11:**

| Suite | Total | Failed | Skipped |
|---|---:|---:|---:|
| `DemoPos.Tests` | 116 | 0 | 0 |
| `StaffApp.Tests` | 84 | 0 | 0 |
| `DemoConsole.Tests` | 165 | 0 | 0 |

---

## 6. Reset the demo database, then smoke

```powershell
docker compose up -d --wait sqlserver
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1
```

The reset script stops `middleware`, `pos-gateway` and `hq-demo`, recreates `RTS_DB_DEMO` and `RTS_HQ`, registers the POS fingerprints, issues the 13 demo tokens into `.tokens/demo_tokens.json`, loads 90 days of `HIST-` history (seed 42) and moves a few batch expiries to the business date. It takes about 45 seconds.

Then, with the middleware healthy on `https://127.0.0.1:8443/api/v1/health`:

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware `
  python scripts/demo/sprint2_smoke.py
```

Run it **twice**; both must be all PASS and end with `ALL CHECKS PASSED`. It exits 1 on any failure. Run it twice because the second run proves it is repeatable on the same database, which is exactly the state the demo will be in after a rehearsal.

Then **reset once more**, because the smoke test writes sales into `RTS_DB_DEMO`: without this second reset the acts below start on stock the smoke run already changed, and act 2's `40 → 38` is no longer true.

`-DemoMode` prints the env lines the demo needs; `-NoBuild` runs offline from images already on the machine.

---

## 6a. PB-41-10 job pass — forecast and recommendation

The reset script runs the `forecast` job itself when the job exists on this commit, so the forecast may already be in place when §6 finishes. The `recommendation` job is **not** part of the reset, so the proposal set that act 6 accepts and rejects only exists after it has been run. PB-41-10 requires both, so run them explicitly and record the counts rather than assuming the reset covered it.

**Record counts after the reset, before the jobs** — all four lines are what a correct reset prints or shows (`Sprint_3_Demo.md` §1.4):

| Check | Expected |
|---|---|
| Store stock | `STORE-DN1` 360, `STORE-DN2` 225, `STORE-DN3` 135 (9 SKUs per store, 40/25/15) |
| `history_transactions` | 2320, from 90 days ago to yesterday |
| `hq_batches` / `hq_total_rows` | 0 / 0 |
| Reset script's own line | `Forecast job ran.` or `Forecast skipped: no forecast job on main yet.` |

**Run the two jobs** with the middleware healthy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_job.ps1 -Name forecast
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_job.ps1 -Name recommendation
```

Both answer when the job ends and print one line in the form `HTTP <status>   code: <code>   <body>`. A PASS is `HTTP 200` with `{"job":"forecast","status":"COMPLETED"}` (and the same shape for `recommendation`). A `404` means the daily job is not registered on this middleware — record it as a deployment gap, do not treat it as a PASS. Re-running `forecast` is safe: it skips a SKU that already has a forecast row for today (`middleware/app/repositories/forecast.py:58-63`), so the 27-row expectation below does not double.

**Count again after the jobs and record both readings:**

| Table | Expected after the jobs |
|---|---|
| `forecast` | one row per store and SKU with `horizon_days = 7` (`middleware/app/services/forecast.py:16`) — 27 rows on the 9-SKU seed |
| `recommendation` | a non-zero `PENDING` set for at least the near-expiry Dairy/Bakery batches |
| `near_expiry_alert` | a non-zero open set; `Sponge cake` `EXPIRED` first at DN1 and DN2 (`Sprint_3_Demo.md` §4 Màn 6) |

The same numbers are read from the console **Job** tab and, for the forecast, from the console forecast grid.

**If the catalogue changes before the freeze**, the counts above are void. `UAT_Capstone_1_List.md` §11.1 records that `main` seeds 9 products in 3 categories; if the PB-52/PB-53 work lands the 30-product/six-category seed the brief describes, the forecast becomes one row per store and SKU (90 rows at 30 SKUs × 3 stores, not 27), and the near-expiry, recommendation and guardrail samples all have to be re-run. Every figure in `docs/reports/` was measured on the 9-SKU seed, so a new catalogue invalidates the comparison until those jobs are re-run on it.

**Two parts of the brief's Màn 6 that cannot be run on `main`:**

- The Staff App has **no `Dự báo` tab** — four tabs only, verified in `clients/staff-app/StaffApp/UI/MainForm.cs:81-84` and in `UAT_Capstone_1_List.md` §11.1. The forecast is visible only as a **grid** on the demo console's **Job** tab. Record the forecast there, and state in the report that the Staff App tab does not exist on `main`.
- `docs/demo/Sprint_3_Demo.md` §4 **Màn 6 has four steps, not eight**, so there is no "Màn 6 bước 8" to run. Steps 1 and 4 are the near-expiry and forecast jobs above; steps 2 and 3 are the threshold change and the cross-store lookup. Run all four and record them per step.

---

## 7. One pass of acts 2–7 on S, A, B

Use `UAT_Capstone_1_List.md` as the checklist — it is the same acts, in order, with the expected results and case ids. Tick it as a regression run, not as a UAT: the point is to confirm the frozen commit behaves like the one tested, not to discover new defects.

Act 6 depends on §6a: the recommendation proposal that step 6.5 accepts and rejects only exists after the recommendation job has run.

Record for each act: PASS, or the deviation with the issue number.

---

## 8. Reset again for the video

After the regression, reset `RTS_DB_DEMO` once more so 1/12 recording starts from a clean 40/25/15 and a clean alert/recommendation set. Do not record on the regression end-state.

---

## 9. What goes in the "Regression v1.0" issue

1. The exact commit: `git rev-parse HEAD` and `git describe --tags`.
2. The five suite results as a table, each with the command that produced it.
3. The two reset + smoke results, and the §6a count readings before and after the two jobs.
4. The acts 2–7 pass/fail table.
5. Any deviation, with its issue number, or the words "no deviation".

A regression report without the commands is not reproducible and should not be accepted.

---

## 10. Known limits of this runbook

- It does not cover the three-machine LAN rehearsal. That is a separate pre-demo step and needs the router, static IPs and regenerated certificates.
- The 27/11 evidence was collected on `a5f509b`, not on the eventual `v1.0` tag. The frozen run must be repeated on the tag; the 27/11 numbers are the reference point, not a substitute.
- The regression cannot cover PB-51/52/53: they are not on `main` (`UAT_Capstone_1_List.md` §11.1). If they merge before 12:00 30/11, add their lines and re-run the affected suites.
