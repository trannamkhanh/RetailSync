# Demo POS — RetailSync (PB-45 phần 1)

Ứng dụng WinForms .NET 8 mô phỏng máy POS của cửa hàng, dùng cho demo tiến độ ngày 07/11/2026.
Ứng dụng gửi sự kiện `SALE`, `RETURN`, `CANCELLATION` qua **POS gateway** (mTLS, cổng 9443) và đọc
hai panel giám sát trực tiếp từ middleware (cổng 8443).

```text
Thu ngân bán hàng trên Demo POS ──(client certificate, 9443)──> pos-gateway ──> middleware ──> SQL Server
                                      Monitor (staff/auditor, 8443) ──────────────^
```

## 1. Yêu cầu

| Thành phần | Ghi chú |
|---|---|
| Windows | WinForms chỉ chạy trên Windows |
| .NET 8 SDK (hoặc SDK mới hơn có runtime 8) | `dotnet --list-sdks`; máy hiện có SDK 10 + runtime 8 vẫn build được |
| Docker Desktop | Chạy SQL Server, middleware và pos-gateway |
| Git Bash | Có `openssl` để chạy `scripts/generate_dev_certs.sh` |
| Python | Chỉ cần bên trong container middleware; không cần cài trên Windows |

## 2. Chuẩn bị hệ thống (một lần cho mỗi database demo)

Từ thư mục gốc repo, trên `main` mới nhất:

```powershell
docker compose up -d --wait sqlserver
docker compose run --rm migrate
```

Tạo database sạch cho demo (tuỳ chọn, nếu muốn tồn kho bắt đầu đúng 40/25/15):

```powershell
$env:DB_NAME = "RTS_DB_DEMO"
docker compose run --rm migrate
Remove-Item Env:DB_NAME
```

Sau đó mở `.env` và đặt `DB_NAME=RTS_DB_DEMO` (hoặc database bạn vừa tạo).

### 2.1. Thêm gateway secret

Chỉ thêm một lần; không commit `.env`:

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
Add-Content .env ("POS_GATEWAY_SECRET=" + (-join ($bytes | ForEach-Object { $_.ToString('x2') })))
```

### 2.2. Sinh chứng chỉ

Chạy bằng Git Bash, đúng thư mục gốc repo:

```powershell
& "$env:ProgramFiles\Git\bin\bash.exe" scripts/generate_dev_certs.sh
```

Kết quả: `.certs/ca.crt`, `.certs/server.crt|key`, và 6 cặp `.certs/pos/POS-DN*-*.crt|key`.

### 2.3. Đăng ký fingerprint và cấp token

```powershell
docker compose build middleware
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python scripts/register_pos_certificates.py
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/issue_demo_tokens.py
```

Lệnh đăng ký đọc `DB_NAME` trong `.env`; nếu đổi database demo, **phải chạy lại lệnh này**.
Token được ghi vào `.tokens/demo_tokens.json` (13 khóa: 6 POS, `staff_dn1..3`, `manager_dn1`,
`admin`, `auditor`, `hq_operator`).

### 2.4. Khởi động middleware và gateway

```powershell
docker compose up -d --wait middleware pos-gateway
```

Kiểm tra nhanh:

```powershell
curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://localhost:8443/api/v1/health
```

Kỳ vọng `{"status":"ok"}`. Gọi cổng 9443 không kèm client certificate phải trả **400** của nginx.

## 3. Chạy ứng dụng

Từ thư mục gốc repo:

```powershell
dotnet run --project clients/demo-pos/DemoPos/DemoPos.csproj
```

Ứng dụng tự tìm repo root bằng cách đi ngược từ thư mục executable đến nơi có `compose.yaml`.
Nếu thiếu CA, certificate của một terminal hoặc file token, ứng dụng hiện đúng lệnh cần chạy và
không khởi động (trừ chế độ MOCK).

### Cấu hình

`DemoPos/appsettings.json` (đã commit, không chứa token hay secret) gồm:

| Khóa | Ý nghĩa |
|---|---|
| `PosBaseUrl` | `https://localhost:9443/api/v1` — gửi sự kiện qua gateway |
| `MonitorBaseUrl` | `https://localhost:8443/api/v1` — đọc tồn kho/audit |
| `TrustedCertificatePath` | `.certs/ca.crt` — chỉ tin CA này |
| `ClientCertificateDir` | `.certs/pos` — nơi có `<pos_id>.crt|key` |
| `TokensPath` | `.tokens/demo_tokens.json` |
| `UseMock` | `false` khi demo thật |
| `Terminals` | 6 terminal: store id, store name, POS id |
| `Products` | 9 SKU đúng seed `database/seed/002_demo_catalog.sql` |

Muốn đổi cấu hình mà không sửa file đã commit, tạo `DemoPos/appsettings.Local.json` (đã git-ignore);
file này được merge đè lên `appsettings.json`.

## 4. Bố trí màn hình demo

| Cửa sổ | Lệnh | Khán giả thấy |
|---|---|---|
| Demo POS | `dotnet run --project clients/demo-pos/DemoPos/DemoPos.csproj` | POS, monitor, terminals table, request log |
| Terminal 1 | `docker compose ps` | `sqlserver`, `middleware`, `pos-gateway` đang chạy |
| Terminal 2 | `docker compose logs -f --tail 0 middleware pos-gateway` | Mỗi request đến gateway và middleware |
| Terminal 3 | Lệnh `db_snapshot.py` bên dưới | Dòng giao dịch, tồn kho và audit mới |

Terminal 3 (PowerShell, từ thư mục gốc repo):

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python clients/demo-pos/tools/db_snapshot.py --store STORE-DN1 --watch 2
```

`db_snapshot.py` chỉ chạy `SELECT`; nó dùng `app.core.db.SessionLocal` và in 3 bảng: 5 giao dịch
gần nhất, tồn kho của store, 5 dòng audit gần nhất.

## 5. Các bước demo chính

1. Chọn `POS-DN1-01`, thêm 2 × `SKU-0001`, bấm **Pay**. Kỳ vọng `OK`, tồn 40 → 38, audit `STOCK_CHANGE`.
2. Chọn dòng SALE vừa gửi, bấm **Send again**. Kỳ vọng `DUPLICATE`, tồn vẫn 38, audit `DUPLICATE_EVENT`.
3. Chọn dòng SALE, bấm **Return…**, trả 1. Kỳ vọng `OK`, tồn 39.
4. Mở **Scenarios (F12)** và chạy từng kịch bản; so mã với nhãn trên nút.
5. Bán một đơn mới rồi bấm **Cancel** (đơn chưa có Return). Kỳ vọng `OK`, tồn trở lại như trước.
6. Tắt gateway, bán hàng: sự kiện được lưu và hiển thị đang chờ. Bật gateway: hàng đợi tự gửi lại
   theo thứ tự với cùng `transaction_id`. Nhấn số sự kiện bị từ chối ở thanh trạng thái để xem chi tiết.

Nút **Bật tự động** gửi SALE cho terminal đang chọn theo chu kỳ (giây) và hiển thị seed; bấm lại để dừng.
Trong chế độ LIVE, mỗi terminal lưu hàng đợi tại `%LOCALAPPDATA%\RetailSync\DemoPos\` trước khi gửi.
Sau khi khởi động lại, các sự kiện còn chờ được gửi tiếp. Các giao dịch bị từ chối được giữ trong danh sách
để thu ngân kiểm tra; kết quả `OK` và `DUPLICATE` được xóa khỏi hàng đợi.

Mỗi lần gửi, **Request log** hiện method, URL đầy đủ kèm port, status, thời gian, request/response
và certificate đã dùng. Log không bao giờ hiển thị bearer token; chỉ hiện role/subject.
Bộ lọc mặc định chỉ hiện POS event và kịch bản; chọn “Tất cả” để xem cả monitor/health.

## 6. Kịch bản ẩn sau F12

| Nút | Request | Kỳ vọng |
|---|---|---|
| Conflict | Gửi lại `transaction_id` của SALE gần nhất, khác số lượng | 409 `CONFLICT` |
| Bán 999 | SALE 999 đơn vị | 409 `INSUFFICIENT_STOCK` |
| Store lạ | `store_id=STORE-XX`, giữ `pos_id` đã đăng ký | 422 `UNREGISTERED_STORE_OR_POS` |
| Trả quá số | RETURN nhiều hơn số đã bán/đã trả | 409 `RETURN_QTY_EXCEEDED` |
| Sai chứng chỉ | SALE của terminal đang chọn nhưng gửi bằng cert terminal khác | 403 `FORBIDDEN` |
| Không chứng chỉ | SALE tới 9443 không kèm cert | 400 của gateway |
| Bỏ qua gateway | SALE thẳng tới 8443 | 403 `FORBIDDEN` |

- Sai chứng chỉ có audit `EVENT_REJECTED`; không chứng chỉ và bỏ qua gateway thì không có audit.
- “Bán 999”, Conflict, Store lạ và Trả quá số không làm đổi tồn kho.

## 7. Chế độ MOCK (dự phòng)

Nút **Bật MOCK (dự phòng)** trong bảng Scenarios chuyển ứng dụng sang backend trong bộ nhớ. Tiêu đề
cửa sổ và result panel hiện **MOCK** thật lớn để không nhầm với dữ liệu thật. Chế độ này dùng khi
middleware/Docker lỗi trên máy demo; nói rõ với người xem và chiếu video diễn tập.

## 8. Kiểm thử

```powershell
dotnet test clients/demo-pos/DemoPos.sln
```

Test phủ: JSON sự kiện (snake_case, `timestamp` kết thúc `Z`, CANCELLATION không items, transaction id),
parse `OK`/`DUPLICATE`/`Error`/body không JSON, chuỗi tin cậy CA, loader certificate, thiếu token file,
request log không chứa bearer token, và luật nghiệp vụ của mock backend.

## 9. Xử lý sự cố

| Hiện tượng | Việc cần làm |
|---|---|
| 403 `FORBIDDEN` khi gửi POS | Kiểm tra `POS_GATEWAY_SECRET` trong `.env`, đã chạy `register_pos_certificates.py` cho đúng DB chưa, và đang dùng đúng cert của terminal |
| 400 của gateway | Request thiếu client certificate; xem lại `.certs/pos/<pos_id>.crt|key` |
| Không đọc được chứng chỉ | Chạy lại `scripts/generate_dev_certs.sh`; nếu vừa sinh lại cert, đăng ký lại fingerprint |
| Thiếu token / 401 | Chạy `scripts/issue_demo_tokens.py`; kiểm tra `JWT_SECRET` trong `.env` |
| `Access denied` khi load certificate | Một số môi trường sandbox chặn ghi vào Windows certificate store với exe nằm trong thư mục bị hạn chế. Copy thư mục build ra ngoài workspace (ví dụ `%TEMP%\DemoPos`) rồi chạy, hoặc chạy trên máy Windows thông thường |
| Tồn kho không về 40 | Dùng database demo mới (ví dụ `RTS_DB_DEMO2`), đổi `DB_NAME` trong `.env`, chạy migrate và **đăng ký lại fingerprint** |
| `docker compose up middleware` thoát | Thiếu `.certs/server.crt|key`; chạy lại bước sinh chứng chỉ |
| Không thấy dòng request trong log | Ghi lại vào PR và báo nhóm; **không sửa middleware** trong task này |

## 10. Ghi chú kỹ thuật

- Ứng dụng chỉ tin CA trong `TrustedCertificatePath`; kiểm tra chuỗi bằng `X509Chain` với custom trust
  store, không chấp nhận mọi certificate.
- Client certificate được load bằng `X509Certificate2.CreateFromPemFile(crt, key)`, sau đó re-import
  một lần từ PKCS#12 export để private key dùng được với `SslStream` trên Windows.
- Mỗi terminal có `HttpClient`/handler riêng, nên mỗi request mang đúng certificate của máy đó.
- Timeout request là 5 giây.
- Phần 2 của PB-45 (queue bền, tự động gửi lại, CLI) và Staff App không nằm trong phần này.
