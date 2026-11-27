# PB-41-10 regression on the frozen `main`

**Owner:** Quang · **When:** 30/11, after 12:00 (post-freeze) · **Recorded in:** the GitHub issue "Regression v1.0"
**Base:** the commit tagged `v1.0` (never a later commit)

This runbook is the one that was actually executed on 27/11 against `a5f509b`, so every command below is proven to work on this host. The numbers in §6 are that run's results and are the baseline the frozen run must match or explain.

---

## 0. Two facts that break a naive run

Fix these first or the run will report hundreds of false failures.

1. **`RTS_DB_TEST` can be a migration behind `RTS_DB`.** On 27/11 the suite failed with **221 failed, 32 errors**, all `Invalid column name 'occurred_at'` — the test database had not received `004_pos_transaction_occurred_at.sql`. Migrating it fixed every one of them with no code change. Always run the migration step below, and if a mass failure appears, check for a missing column before believing it is a regression.
2. **`dotnet test` does not work on this host.** The VSTest testhost aborts with `Win32Exception (5): Access is denied` before running a single test. Use the xunit console runner. `scripts/demo/run_console_tests.ps1` covers the demo console only; the demo-pos and staff-app suites need the same treatment (see §4).

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
# application test database
docker compose run --rm -e DB_NAME=RTS_DB_TEST migrate

# HQ test database
docker compose run --rm -e HQ_DB_NAME=RTS_HQ_TEST migrate
```

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

`DemoPos.Tests` and `StaffApp.Tests` have **no committed runner**. Two ways to run them:

- If `scripts/demo/run_client_tests.ps1` exists on the frozen commit, use it for both.
- Otherwise run the xunit console runner directly against the built assemblies, exactly as `run_console_tests.ps1` does (build, drop `xunit.console` into the test bin, write `xunit.console.runtimeconfig.json` for `Microsoft.WindowsDesktop.App`, copy the RID-specific `Microsoft.Data.SqlClient.dll` and `SNI.dll`, then run). The throwaway script used for the 27/11 run did this and is reproduced in `Regression_Evidence_v1.0.md`.

**Results on 27/11:**

| Suite | Total | Failed | Skipped |
|---|---:|---:|---:|
| `DemoPos.Tests` | 116 | 0 | 0 |
| `StaffApp.Tests` | 84 | 0 | 0 |
| `DemoConsole.Tests` | 165 | 0 | 0 |

---

## 6. Reset the demo database, then smoke

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1
```

Then, with the middleware healthy on `https://127.0.0.1:8443/api/v1/health`:

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware `
  python scripts/demo/sprint2_smoke.py
```

Run it **twice**; both must be all PASS. It exits 1 on any failure. Run it twice because the second run proves it is repeatable on the same database, which is exactly the state the demo will be in after a rehearsal. Reset once more afterwards so stock starts at 40/25/15.

`-DemoMode` prints the env lines the demo needs; `-NoBuild` runs offline from images already on the machine.

---

## 7. One pass of acts 2–7 on S, A, B

Use `UAT_Capstone_1_List.md` as the checklist — it is the same acts, in order, with the expected results and case ids. Tick it as a regression run, not as a UAT: the point is to confirm the frozen commit behaves like the one tested, not to discover new defects.

Record for each act: PASS, or the deviation with the issue number.

---

## 8. Reset again for the video

After the regression, reset `RTS_DB_DEMO` once more so 1/12 recording starts from a clean 40/25/15 and a clean alert/recommendation set. Do not record on the regression end-state.

---

## 9. What goes in the "Regression v1.0" issue

1. The exact commit: `git rev-parse HEAD` and `git describe --tags`.
2. The five suite results as a table, each with the command that produced it.
3. The two reset + smoke results.
4. The acts 2–7 pass/fail table.
5. Any deviation, with its issue number, or the words "no deviation".

A regression report without the commands is not reproducible and should not be accepted.

---

## 10. Known limits of this runbook

- It does not cover the three-machine LAN rehearsal. That is a separate pre-demo step and needs the router, static IPs and regenerated certificates.
- The 27/11 evidence was collected on `a5f509b`, not on the eventual `v1.0` tag. The frozen run must be repeated on the tag; the 27/11 numbers are the reference point, not a substitute.
- The regression cannot cover PB-51/52/53: they are not on `main` (`UAT_Capstone_1_List.md` §11.1). If they merge before 12:00 30/11, add their lines and re-run the affected suites.
