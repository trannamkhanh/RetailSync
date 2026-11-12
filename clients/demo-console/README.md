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

## What it reads and how

| Tab | Data | Source |
|---|---|---|
| Tồn và lô | Stock per store and SKU, batches of the selected row | `GET /stores/{id}/inventory` with `staff_dn1`, `staff_dn2`, `staff_dn3` |
| Giao dịch và audit | Latest 30 transactions (history `HIST-` left out), latest 30 audit rows | SQL `pos_transaction`; `GET /audit-logs` with `auditor` |
| Đồng bộ và HQ | `sync_batch` rows, HQ batches and totals | SQL `sync_batch`; `GET /demo/batches` on the HQ demo |
| Job | Open near-expiry alerts, latest forecast per store and SKU | SQL `near_expiry_alert`, `forecast` |

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
- The HQ demo has no API that reads the current mode; the console shows the last
  mode it set. The HQ demo starts in ONLINE.
- A row whose value changed since the previous refresh is yellow for
  `HighlightSeconds` (default 15), and the stock grid shows the old and new value.

## Configuration

`DemoConsole/appsettings.json`: `MiddlewareBaseUrl`, `HqBaseUrl`,
`TrustedCertificatePath`, `TokensPath`, `EnvFilePath`, `SqlServer`, `Database`,
`RefreshSeconds` (default 3), `HighlightSeconds`, `FontSize`, the stores with
their Staff token names, and the product names. Put machine-specific values in
`DemoConsole/appsettings.Local.json` (git-ignored), for example a larger
`FontSize` for the projector.

`DemoConsole/Security/ServerCertificateValidator.cs`, `Services/TokenStore.cs` and
`Configuration/RepoRootLocator.cs` are copies of the demo POS classes, so the two
clients can change apart.
