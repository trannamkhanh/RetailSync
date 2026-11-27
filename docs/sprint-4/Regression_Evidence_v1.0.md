# Regression evidence — 27/11/2026, `a5f509b`

**Run by:** Quang · **Commit:** `a5f509b` (`origin/main`, merge of PR #93) · **Host:** machine S, Docker Desktop
**Databases:** `RTS_DB_TEST`, `RTS_HQ_TEST`. `RTS_DB` was never touched; `DB_NAME` was set to `RTS_DB_NOWRITE` for the suite.
**Status:** all five suites green — **0 failed, 0 skipped, 0 xfail**.

This is a rehearsal of the PB-41-10 runbook on the current `main`, not the post-freeze run. The frozen run must be repeated on the `v1.0` tag; these numbers are the reference it has to match.

---

## 1. Summary

| Suite | Total | Failed | Skipped | xfail |
|---|---:|---:|---:|---:|
| Middleware (pytest) | 1459 | 0 | 0 | 0 |
| HQ demo (pytest) | 28 | 0 | 0 | 0 |
| `DemoConsole.Tests` | 165 | 0 | 0 | 0 |
| `DemoPos.Tests` | 116 | 0 | 0 | 0 |
| `StaffApp.Tests` | 84 | 0 | 0 | 0 |

---

## 2. The false-failure that had to be cleared first

The first middleware run was **221 failed, 1206 passed, 32 errors in 337.29s**. Every failure was the same schema error:

```
sqlalchemy.exc.ProgrammingError: (pyodbc.ProgrammingError) ('42S22', "[42S22] [Microsoft][ODBC Driver 18
for SQL Server][SQL Server]Invalid column name 'occurred_at'. (207) (SQLExecDirectW)")
[SQL: INSERT INTO pos_transaction (txn_id, store_id, pos_id, txn_type, ref_txn_id, status, sync_batch_id,
payload_hash, occurred_at) OUTPUT inserted.effective_at, inserted.created_at VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)]
```

Cause: `RTS_DB_TEST` was one migration behind (`004_pos_transaction_occurred_at.sql` had not been applied). It was an environment state, not a code defect — the base commit itself is green.

Fix, then re-run:

```powershell
docker compose run --rm -e DB_NAME=RTS_DB_TEST -e HQ_DB_NAME=RTS_HQ_TEST migrate
```

`DB_NAME` has to travel with `HQ_DB_NAME` in the same call: on its own the migration falls back to the `.env` value for the application database and would run against `RTS_DB` / `RTS_DB_DEMO`. The 27/11 run above passed only `-e DB_NAME=RTS_DB_TEST` and therefore left `HQ_DB_NAME` at its `.env` default.

Output tail:

```
Applying 004_pos_transaction_occurred_at.sql

(1 rows affected)

(0 rows affected)
(0 rows affected)
Database is up to date
HQ database RTS_HQ is up to date
```

The second run was clean: **1459 passed**.

Lesson for the frozen run: migrate the test databases **before** the suite, and if a mass failure appears with a column name in it, suspect a stale test database before suspecting the commit.

---

## 3. Middleware

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo/middleware `
  --env PYTHONDONTWRITEBYTECODE=1 --env TEST_DB_NAME=RTS_DB_TEST --env DB_NAME=RTS_DB_NOWRITE `
  middleware sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

```
........................................................................ [ 39%]
...
...................                                                      [100%]
1459 passed, 2 warnings in 149.96s (0:02:29)
```

The two warnings are `starlette.testclient` `BlockingPortal` deprecation and `httpx` `verify=<str>` deprecation. Neither is a project defect and neither is a skip.

0 skipped confirms the repository was mounted at `/repo`: without the mount, four tests that read `database/seed` and `scripts/` are skipped.

---

## 4. HQ demo

```powershell
docker compose run --rm --no-deps -e HQ_DB_NAME=RTS_HQ_TEST --volume "${PWD}/hq-demo:/app" --workdir /app `
  hq-demo sh -c 'pip install -q -r requirements-dev.txt && python -m pytest -p no:cacheprovider -q'
```

```
............................                                             [100%]
28 passed, 1 warning in 9.54s
```

---

## 5. `DemoConsole.Tests`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_console_tests.ps1
```

```
Building <worktree>\clients\demo-console\DemoConsole.sln ...
  Discovering: DemoConsole.Tests
  Discovered:  DemoConsole.Tests
  Starting:    DemoConsole.Tests
  Finished:    DemoConsole.Tests
=== TEST EXECUTION SUMMARY ===
   DemoConsole.Tests  Total: 165, Errors: 0, Failed: 0, Skipped: 0, Time: 1.810s
```

---

## 6. `DemoPos.Tests` and `StaffApp.Tests`

`dotnet test` cannot run on this host. Verification that this is an environment limit, not a project defect:

```
Test run for ...\clients\demo-pos\DemoPos.Tests\bin\Debug\net8.0-windows\DemoPos.Tests.dll (.NETCoreApp,Version=v8.0)
dotnet : Testhost process for source(s) '...DemoPos.Tests.dll' exited with error: Unhandled exception.
System.ComponentModel.Win32Exception (5): Access is denied.
   at System.Diagnostics.ProcessManager.OpenProcess(Int32 processId, Int32 access, Boolean throwIfExited)
   at System.Diagnostics.Process.EnsureWatchingForExit()
   at Microsoft.VisualStudio.TestPlatform.TestHost.DefaultEngineInvoker.SetParentProcessExitCallback(...)
Test Run Aborted.
```

No committed runner exists for these two suites (`scripts/demo/` has `run_console_tests.ps1` only, and it hard-codes the console solution). The suites were run with the same xunit-console technique: build the solution, copy the runner into the test output folder, write a `Microsoft.WindowsDesktop.App` runtimeconfig, copy the RID-specific `Microsoft.Data.SqlClient.dll` and `Microsoft.Data.SqlClient.SNI.dll`, then execute the test assembly.

`DemoPos.Tests`:

```
Building ...\clients\demo-pos\DemoPos.sln ...
  Discovering: DemoPos.Tests
  Discovered:  DemoPos.Tests
  Starting:    DemoPos.Tests
  Finished:    DemoPos.Tests
=== TEST EXECUTION SUMMARY ===
   DemoPos.Tests  Total: 116, Errors: 0, Failed: 0, Skipped: 0, Time: 25.180s
```

`StaffApp.Tests`:

```
Building ...\clients\staff-app\StaffApp.sln ...
  Discovering: StaffApp.Tests
  Discovered:  StaffApp.Tests
  Starting:    StaffApp.Tests
  Finished:    StaffApp.Tests
=== TEST EXECUTION SUMMARY ===
   StaffApp.Tests  Total: 84, Errors: 0, Failed: 0, Skipped: 0, Time: 1.660s
```

**Follow-up (not done in this PR):** generalise `run_console_tests.ps1` so `run_client_tests.ps1` exists for `demo-pos` and `staff-app`. Until then the frozen run has to repeat the manual runner steps, which is a source of variance between runs.

---

## 7. Not covered by this run

- `reset_demo_db.ps1` and `sprint2_smoke.py` were **not** executed here: resetting `RTS_DB_DEMO` would have disturbed the running dev stack (`retailsync-*`), which other people were using. They are part of the frozen run, on a stack this run owns.
- Acts 2–7 were not walked; that needs machines A and B.
- The numbers are evidence for **the test suites**, not for the demo.
