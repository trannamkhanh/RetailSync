# Demo console (PB-42-6)

The presenter's window on machine S for the Sprint 3 demo. It is a presenter tool,
not part of the product: it holds the Admin, Auditor and HQ tokens and runs only on
machine S. The runbook is `docs/demo/Sprint_3_Demo.md`.

## Build and run

From the repository root in PowerShell, after `scripts/demo/reset_demo_db.ps1`:

```powershell
dotnet build clients/demo-console/DemoConsole.sln
clients/demo-console/DemoConsole/bin/Debug/net8.0-windows/DemoConsole.exe
```

Tests (no running stack needed):

```powershell
dotnet test clients/demo-console/DemoConsole.sln
```

If `dotnet test` aborts before running anything with
`System.ComponentModel.Win32Exception (5): Access is denied` from the VSTest
testhost, that is the host denying the testhost a handle to its parent process, not
a test failure — the same abort happens on untouched code. Use the console runner
instead, which runs the test assembly in its own process:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_console_tests.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_console_tests.ps1 -Filter "DemoConsole.Tests.DashboardTests.Parses_every_field_of_the_revenue_contract"
```

It builds the solution, downloads `xunit.runner.console` 2.9.2 into the temp folder
once, arranges the runtime and native assets the runner needs (WindowsDesktop
framework, the real `Microsoft.Data.SqlClient.dll` rather than the reference
assembly, and `Microsoft.Data.SqlClient.SNI.dll`), then exits 1 if any test fails so
it can gate a merge. Add `-Rebuild` when a source file's timestamp is older than the
binaries and MSBuild skips recompiling it.

## What it reads and how

| Tab | Data | Source |
|---|---|---|
| Tồn và lô | Stock per store and SKU, batches of the selected row | `GET /stores/{id}/inventory` with `staff_dn1`, `staff_dn2`, `staff_dn3` |
| Giao dịch và audit | Latest 30 transactions (history `HIST-` left out), latest 30 audit rows | SQL `pos_transaction`; `GET /audit-logs` with `auditor` |
| Đồng bộ và HQ | `sync_batch` rows, HQ batches and totals | SQL `sync_batch`; `GET /demo/batches` on the HQ demo |
| Job | Open near-expiry alerts, latest forecast per store and SKU | SQL `near_expiry_alert`, `forecast` |
| Doanh thu (PB-49) | Line per day, category pie, store comparison bars, net total, transaction count, time-quality badge | `GET /dashboard/revenue`, `/dashboard/revenue-by-category`, `/dashboard/revenue-by-store` and `/dashboard/stores` with `admin` |

The **Doanh thu** tab draws the three charts of `Dashboard_Survey_and_Plan.md` §6.5-6.7:

| Chart | Data | Scope |
|---|---|---|
| Đường: Tổng doanh thu theo thời gian | Net revenue per bucket | The view scope |
| Tròn: Tỷ lệ theo danh mục | Share per product category | The view scope |
| Cột: So sánh cửa hàng | One column per store | The comparison set, independent of the view scope |

The pie follows the design's label mapping (`Dairy` → *Sản phẩm từ sữa*, `Bakery` →
*Bánh nướng*, `Dry goods` → *Thực phẩm khô*); an unmapped category keeps its own name.
A category whose net revenue is negative cannot be a share of a whole, so it is left
out of the pie and named in a note under it instead of being silently dropped.

Both the pie and the bar stay in the tab while only the line was in the implementation
plan's D3 scope; the two endpoints were already part of D2, so only the UI was missing.

The tab is the only one that refuses SQL: the revenue rule lives on the server, so the
presenter shows the API answer and never recomputes it. It has its own 30-second timer
(`DashboardRefreshSeconds`), because the other four tabs refresh every 3 seconds and
three range aggregates that often would be a heavy query for charts that only need to
move once a period. The view filter is the scope (whole system, or one store); the bar
always compares the Admin's whole scope, which is the documented default selection.
There is no role picker, so the tab is always the Admin view.

The badge names the two suspect groups and the pre-migration rows, so an approximate
total is never shown as if it were exact. `BACKFILL` counts as trusted;
`SUSPECT_FUTURE`, `SUSPECT_OLD` and `unknown` do not, and the API returns their counts
even when the money came from `include_suspect=false`.

Buttons: **Chạy đồng bộ** (`POST /sync/run`, admin), one button per HQ mode
(`PUT /demo/mode`), **Gửi snapshot** (`POST /hq/snapshot`, hq_operator), **Chạy
kiểm tra cận hạn** and **Chạy dự báo** (`POST /admin/jobs/{name}/run`, admin),
**Đặt ngưỡng** (`PUT /admin/near-expiry-thresholds/{category}`, admin). The answer
(status, code, message) appears in the line at the bottom.

- SQL is SELECT only: four constant statements with parameters, each in a
  transaction that is rolled back, as `sa` with `MSSQL_SA_PASSWORD` from `.env`.
- The console connects to the database in `Database` (default `RTS_DB_DEMO`) and
  refuses `RTS_DB` and `RTS_DB_TEST`.
- A route that is not on main yet shows its button disabled with the reason. Routes
  are probed every 30 seconds with a GET that changes nothing (405 means the route
  exists, 404 that it does not), so after a pull request merges and the middleware
  restarts the button turns on without a new build. A job route exists for every
  name, so a job button turns off only when pressing it answers 404 `NOT_FOUND`.
  The revenue tab follows the same rule: a 404 from `/dashboard/revenue` disables
  its filters and shows the reason.
- The HQ demo has no API that reads the current mode; the console shows the last
  mode it set. The HQ demo starts in ONLINE.
- A row whose value changed since the previous refresh is yellow for
  `HighlightSeconds` (default 15), and the stock grid shows the old and new value.

## Configuration

`DemoConsole/appsettings.json`: `MiddlewareBaseUrl`, `HqBaseUrl`,
`TrustedCertificatePath`, `TokensPath`, `EnvFilePath`, `SqlServer`, `Database`,
`RefreshSeconds` (default 3), `DashboardRefreshSeconds` (default 30),
`HighlightSeconds`, `FontSize`, the stores with their Staff token names, and the
product names. Put machine-specific values in `DemoConsole/appsettings.Local.json`
(git-ignored), for example a larger `FontSize` for the projector.

## Charting dependency

The revenue line uses `LiveChartsCore.SkiaSharpView.WinForms 2.0.5`, which pulls in
the native SkiaSharp assets. The first build needs Internet for the NuGet restore,
so run `dotnet build` on machine S before the demo and confirm
`bin/Debug/net8.0-windows` contains `SkiaSharp.dll` and `libSkiaSharp.dll`. If the
chart fails to paint on the projector, fall back to OxyPlot rather than cutting the
tab from the demo.

`DemoConsole/Security/ServerCertificateValidator.cs`, `Services/TokenStore.cs` and
`Configuration/RepoRootLocator.cs` are copies of the demo POS classes, so the two
clients can change apart.
