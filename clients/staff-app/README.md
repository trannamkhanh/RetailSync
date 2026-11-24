# Staff App (PB-46, PB-47, PB-50)

WinForms client (.NET 8) for store staff, following `docs/design/DS-08_Staff_App_Wireframes.html`.
One window, four tabs, with a Vietnamese UI (PB-46-5):

| Tab | Calls (DS-04) | Test cases |
|---|---|---|
| Tra cứu (lookup) | `GET /products/barcode/{barcode}`, `GET /products/barcode/{barcode}/stock?from_store=` | STF46-1, 46-2, 46-3 |
| Cảnh báo cận hạn (near-expiry alerts) | `GET /near-expiry-alerts` | STF46-4 |
| Đề xuất (recommendations, list and details) | `GET /recommendations`, `GET /recommendations/{rec_id}`, `POST /recommendations/{rec_id}/decision` | STF47-1 to 47-5 |
| Giảm giá (active discounts, read-only) | `GET /staff/discounts?scope=own` or `?scope=all` | DSC50-* |

The app calls only these endpoints, over HTTPS on port 8443, with one `staff_dn*` token. The store comes
from the token's `store_id`; the title bar shows the store and the account. It never reads SQL.
Messages follow DS-08, in Vietnamese: 401 "Token không hợp lệ hoặc đã hết hạn" (STF46-5), 403 "Vai trò
này không dùng được chức năng này", 404 on lookup "Không tìm thấy sản phẩm", 409 `ALREADY_DECIDED` "Đề xuất
đã được quyết định", `RECOMMENDATION_EXPIRED` "Đề xuất không còn hiệu lực" (both refresh the list). A
connection error keeps the screen and shows Thử lại in the status bar. API codes, product names and the
server's reason text stay as sent.

## Configuration

`StaffApp/appsettings.json` (committed), overridden key by key by `appsettings.Local.json` next to the
exe (git-ignored). Relative paths are relative to the app folder.

| Key | Default | Meaning |
|---|---|---|
| `BaseUrl` | `https://localhost:8443/api/v1` | Middleware API; on machine A `https://<IP of S>:8443/api/v1` |
| `CaCertificatePath` | `ca.crt` | The development CA, `.certs/ca.crt` of machine S |
| `TokenFile` | `staff_token.txt` | One token on one line, or a JSON object of tokens such as `.tokens/demo_tokens.json` |
| `TokenName` | `staff_dn1` | The key read when `TokenFile` is a JSON object |
| `FontSize` | `12` | Base font size (8 to 32) |

`staff_token.txt`, `ca.crt` and `appsettings.Local.json` are git-ignored in this folder. Never commit a
token.

## Build, test, run

```powershell
dotnet build clients/staff-app/StaffApp.sln
```

```powershell
dotnet test clients/staff-app/StaffApp.sln
```

The tests use fake HTTP answers that follow DS-04; none needs the running stack.

To run outside the repository (machine A), publish once and copy the folder:

```powershell
dotnet publish clients/staff-app/StaffApp/StaffApp.csproj -c Release -o C:\RetailSync\StaffApp
```

Then put `ca.crt` in `C:\RetailSync\StaffApp` and create `appsettings.Local.json` there, for example:

```json
{
  "BaseUrl": "https://192.168.1.10:8443/api/v1",
  "TokenFile": "C:\\RetailSync\\RetailSync\\.tokens\\demo_tokens.json",
  "TokenName": "staff_dn1"
}
```

Run `C:\RetailSync\StaffApp\StaffApp.exe`.
