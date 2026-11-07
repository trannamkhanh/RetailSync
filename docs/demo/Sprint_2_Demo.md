# Kịch bản demo Sprint 2

Demo chiều 13/11/2026, khoảng 25 phút. Mỗi người trình bày phần backlog của mình; các bước
dưới đây chạy trên **database demo riêng** (`RTS_DB_DEMO`), tồn kho bắt đầu đúng 40/25/15.

Kịch bản dùng đúng các API đã merge trên `main`: HTTPS 8443 cho Staff/Admin/Auditor và
POS gateway mutual TLS 9443 cho máy POS.

## 1. Chuẩn bị trước buổi demo (làm trước 30 phút)

Từ thư mục gốc repo, trong PowerShell:

```powershell
# 1. Bật Docker Desktop, đợi engine xanh
docker compose up -d --wait sqlserver

# 2. Tạo lại database demo sạch và cấp token
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1

# 3. Trỏ middleware vào database demo: sửa .env thành DB_NAME=RTS_DB_DEMO
#    (không commit .env), rồi khởi động lại hai service
docker compose up -d --force-recreate --wait middleware pos-gateway

# 4. Build app Demo POS (một lần, hoặc sau khi sửa code client)
dotnet build clients/demo-pos/DemoPos/DemoPos.csproj -c Debug

# 5. Chạy smoke check hai lần liên tiếp, cả hai phải PASS
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/demo/sprint2_smoke.py
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/demo/sprint2_smoke.py

# 6. Chạy smoke hai lần làm tồn kho giảm, nên reset lại lần cuối để demo bắt đầu từ 40/25/15
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1
docker compose up -d --force-recreate --wait middleware pos-gateway
```

Kết quả đúng: cả hai lần smoke kết thúc bằng `ALL CHECKS PASSED`; lần reset cuối in
`Database RTS_DB_DEMO is ready. The stock is back to the seeded 40/25/15.`

Mở sẵn trước khi bắt đầu:

- `clients/demo-pos/DemoPos/bin/Debug/net8.0-windows/DemoPos.exe` (máy POS).
- Một cửa sổ PowerShell tại thư mục gốc repo (để chạy lệnh API ở mục 2.1).
- Sprint Backlog và file kết quả test case.
- Video diễn tập (dự phòng khi máy hoặc mạng lỗi).

Kiểm tra nhanh cuối cùng:

```powershell
docker compose ps
curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://127.0.0.1:8443/api/v1/health
```

## 2. Mười bốn bước demo

Thời lượng gợi ý 12–15 phút. Tồn kho ghi **tương đối** so với trước bước đó, nên kịch bản
đúng dù database vừa được reset hay vừa chạy smoke. Cột "Chứng minh" ghi backlog và mã test
case trong `GROUP_08_Test case.xlsx`; case phụ thuộc Sprint 3 trở đi (ví dụ lô hàng) ghi
`Not Implemented` trong báo cáo, không demo.

| # | Người | Thao tác | Kết quả mong đợi | Chứng minh |
|---|---|---|---|---|
| 1 | Kiệt | Gọi health | `200 {"status":"ok"}` | PB-02-1 |
| 2 | Kiệt | Gọi tồn kho không token; gọi route Admin bằng token Staff | `401 UNAUTHORIZED`; `403 FORBIDDEN` | PS02-1, PS02-4, PS02-7 |
| 3 | Khánh | Đăng ký store `DM-DEMO`, terminal `DM-POS-DEMO`; gửi lại store đó | `201`, `201`, rồi `409 ALREADY_EXISTS` | PB-08 |
| 4 | Quang | Trên Demo POS: chọn `POS-DN1-01`, thêm 2 × `SKU-0001`, bấm **Pay** | `200 OK`, tồn `−2` | POS05-1, PS48-6 |
| 5 | Sang | Chọn đúng dòng SALE vừa gửi trong lịch sử, bấm **Send again** | `200 DUPLICATE_IGNORED`, tồn không đổi | PB-09, POS09-1, POS09-2 |
| 6 | Sang | Gửi cùng `transaction_id` nhưng đổi số lượng | `409 CONFLICT`, tồn không đổi | POS09-4 |
| 7 | Quang | Bán 999 × `SKU-0001` | `409 INSUFFICIENT_STOCK`, tồn không đổi | POS05-7, PS04-3 |
| 8 | Quang / Sang | Trả 1 × `SKU-0001` của đơn A; sau đó bán 3 × `SKU-0002` rồi hủy đơn B | Return `200`, tồn `+1`; hủy `200`, `SKU-0002` về đúng số cũ | PB-06 POS06-1; PB-07 POS07-1 |
| 9 | Sang | Hủy đơn A (đã có return) | `409 SALE_HAS_RETURNS` | PB-07, POS07-5 |
| 10 | Khánh | Staff `staff_dn1` đọc tồn `STORE-DN1`, rồi đọc `STORE-DN2` | `200` (9 SKU), rồi `403 FORBIDDEN` | PB-12, INV12-1, INV12-3 |
| 11 | Sang | Tra barcode `8930000000011` | `200`, `SKU-0001 Fresh milk 1L`, tồn hiện tại | PB-31, STF31-1 |
| 12 | Khánh | Admin đặt `MAX_DISCOUNT` = 150, rồi 40, rồi trả lại 50 | `422` nêu `threshold`; `200` threshold 40; `200` threshold 50 | PB-26, REC26-2, REC26-3 |
| 13 | Kiệt | Gửi POS event không kèm client certificate; sau đó dùng certificate `POS-DN2-01` cho event của `POS-DN1-01` | Gateway trả `400`; middleware trả `403 FORBIDDEN` | PS48-4, PS48-5 |
| 14 | Kiệt | Auditor đọc `/audit-logs`, lọc các bản ghi của lần chạy này; Staff đọc audit | `200`, thấy `STOCK_CHANGE`, `DUPLICATE_EVENT`, `EVENT_REJECTED`, `STORE_REGISTERED`, `POS_REGISTERED`, `GUARDRAIL_RULE_UPDATED`; Staff `403` | PB-04, PS04-1, PS04-3, PS04-4, PS04-6 |

Ghi chú khi trình bày:

- Bước 4 là bước duy nhất phải bấm trên giao diện Demo POS; các bước còn lại có thể chạy bằng
  PowerShell để giữ nhịp.
- Bước 5 phải chọn dòng SALE trong lịch sử rồi bấm **Send again**; bấm **Pay** sẽ tạo giao dịch
  mới, không phải duplicate.
- Bước 12 phải trả `MAX_DISCOUNT` về **50** trước khi sang bước 13; smoke check tự làm việc này.

### 2.1. Lệnh cho từng bước

Chạy một lần ở thư mục gốc repo để nạp biến và hàm dùng chung:

```powershell
cd D:\CapstoneRetaiSync\RetailSync
$mw = "https://127.0.0.1:8443/api/v1"
$gw = "https://127.0.0.1:9443/api/v1/pos/events"
$ca = ".certs/ca.crt"
$t  = Get-Content .tokens/demo_tokens.json -Raw | ConvertFrom-Json
$run = Get-Date -Format "ddHHmmss"

function Send-Pos($json, $cert = "POS-DN1-01", $token = $cert) {
    curl.exe -sS --ssl-no-revoke --cacert $ca `
        --cert ".certs/pos/$cert.crt" --key ".certs/pos/$cert.key" `
        -H "Authorization: Bearer $($t.$token)" -H "Content-Type: application/json" `
        -d $json $gw
}
```

**Bước 1 — health:**
```powershell
curl.exe -sS --ssl-no-revoke --cacert $ca "$mw/health"
```

**Bước 2 — không token và sai role:**
```powershell
curl.exe -sS -o NUL -w "%{http_code}`n" --ssl-no-revoke --cacert $ca "$mw/stores/STORE-DN1/inventory"
curl.exe -sS -o NUL -w "%{http_code}`n" --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.staff_dn1)" "$mw/admin/guardrail-rules"
```

**Bước 3 — đăng ký store, terminal, rồi gửi lại store:**
```powershell
$store = '{"store_id":"DM-DEMO","name":"Cua hang demo","latitude":16.0678,"longitude":108.2208,"region_id":"TEST"}'
curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.admin)" -H "Content-Type: application/json" -d $store "$mw/admin/stores"
curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.admin)" -H "Content-Type: application/json" -d '{"pos_id":"DM-POS-DEMO","store_id":"DM-DEMO"}' "$mw/admin/pos-terminals"
curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.admin)" -H "Content-Type: application/json" -d $store "$mw/admin/stores"
```

**Bước 4 — SALE 2 × SKU-0001 qua gateway:**
```powershell
$saleA = '{"event_type":"SALE","transaction_id":"TXN-DEMO-' + $run + '-A","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:00:00Z","items":[{"sku":"SKU-0001","quantity":2,"unit_price":32000.00}]}'
Send-Pos $saleA
```

**Bước 5 — gửi lại đúng JSON đó (duplicate):**
```powershell
Send-Pos $saleA
```

**Bước 6 — cùng transaction_id, khác số lượng (conflict):**
```powershell
$saleA3 = '{"event_type":"SALE","transaction_id":"TXN-DEMO-' + $run + '-A","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:00:00Z","items":[{"sku":"SKU-0001","quantity":3,"unit_price":32000.00}]}'
Send-Pos $saleA3
```

**Bước 7 — bán 999:**
```powershell
$big = '{"event_type":"SALE","transaction_id":"TXN-DEMO-' + $run + '-BIG","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:00:00Z","items":[{"sku":"SKU-0001","quantity":999,"unit_price":32000.00}]}'
Send-Pos $big
```

**Bước 8 — RETURN đơn A, rồi SALE B và CANCELLATION B:**
```powershell
$returnA = '{"event_type":"RETURN","transaction_id":"TXN-DEMO-' + $run + '-R","original_transaction_id":"TXN-DEMO-' + $run + '-A","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:01:00Z","items":[{"sku":"SKU-0001","quantity":1,"unit_price":32000.00}]}'
Send-Pos $returnA

$saleB = '{"event_type":"SALE","transaction_id":"TXN-DEMO-' + $run + '-C","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:02:00Z","items":[{"sku":"SKU-0002","quantity":3,"unit_price":45000.00}]}'
Send-Pos $saleB

$cancelB = '{"event_type":"CANCELLATION","transaction_id":"TXN-DEMO-' + $run + '-CXL","original_transaction_id":"TXN-DEMO-' + $run + '-C","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:03:00Z"}'
Send-Pos $cancelB
```

**Bước 9 — hủy đơn A đã có return:**
```powershell
$cancelA = '{"event_type":"CANCELLATION","transaction_id":"TXN-DEMO-' + $run + '-CXL-A","original_transaction_id":"TXN-DEMO-' + $run + '-A","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:04:00Z"}'
Send-Pos $cancelA
```

**Bước 10 — tồn kho theo store:**
```powershell
curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.staff_dn1)" "$mw/stores/STORE-DN1/inventory"
curl.exe -sS -o NUL -w "%{http_code}`n" --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.staff_dn1)" "$mw/stores/STORE-DN2/inventory"
```

**Bước 11 — barcode:**
```powershell
curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.staff_dn1)" "$mw/products/barcode/8930000000011"
```

**Bước 12 — guardrail MAX_DISCOUNT:**
```powershell
$rules = curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.admin)" "$mw/admin/guardrail-rules" | ConvertFrom-Json
$rule = $rules.items | Where-Object { $_.rule_type -eq "MAX_DISCOUNT" -and -not $_.category } | Select-Object -First 1
foreach ($value in 150, 40, 50) {
    curl.exe -sS --ssl-no-revoke --cacert $ca -X PUT -H "Authorization: Bearer $($t.admin)" -H "Content-Type: application/json" `
        -d "{`"threshold`":$value,`"is_active`":true}" "$mw/admin/guardrail-rules/$($rule.rule_id)"
    ""
}
```

**Bước 13 — không chứng chỉ, và sai chứng chỉ:**
```powershell
$noCert = '{"event_type":"SALE","transaction_id":"TXN-DEMO-' + $run + '-NC","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:05:00Z","items":[{"sku":"SKU-0001","quantity":1,"unit_price":32000.00}]}'
curl.exe -sS -o NUL -w "%{http_code}`n" --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.'POS-DN1-01')" -H "Content-Type: application/json" -d $noCert $gw

$wrongCert = '{"event_type":"SALE","transaction_id":"TXN-DEMO-' + $run + '-WC","store_id":"STORE-DN1","pos_id":"POS-DN1-01","timestamp":"2026-11-13T09:05:00Z","items":[{"sku":"SKU-0001","quantity":1,"unit_price":32000.00}]}'
Send-Pos $wrongCert "POS-DN2-01" "POS-DN1-01"
```

**Bước 14 — audit:**
```powershell
curl.exe -sS --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.auditor)" "$mw/audit-logs?limit=20"
curl.exe -sS -o NUL -w "%{http_code}`n" --ssl-no-revoke --cacert $ca -H "Authorization: Bearer $($t.staff_dn1)" "$mw/audit-logs"
```

## 3. Bản rút gọn 7 bước (khi thiếu thời gian)

Nếu buổi báo cáo bị chậm, bỏ các bước 1, 2, 3, 6, 9, 11, 12 và chỉ giữ:

| # | Nội dung | Người |
|---|---|---|
| 4 | SALE qua gateway, tồn `−2` | Quang |
| 5 | Gửi lại bằng Send again, DUPLICATE | Sang |
| 7 | Bán vượt tồn, INSUFFICIENT_STOCK | Quang |
| 8 | RETURN và CANCELLATION | Quang / Sang |
| 10 | Tồn kho giới hạn theo store | Khánh |
| 13 | mTLS: không cert 400, sai cert 403 | Kiệt |
| 14 | Audit log đủ hành động | Kiệt |

Lệnh tương ứng vẫn dùng các block ở mục 2.1.

## 4. Khi có sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Mất mạng hoặc Docker Desktop dừng | Chuyển sang video diễn tập, giữ phần thuyết trình |
| `/health` không trả lời | `docker compose ps`; nếu service dừng: `docker compose up -d --wait sqlserver middleware pos-gateway` |
| POS trả `403 FORBIDDEN` | Database demo chưa đăng ký fingerprint: chạy lại `reset_demo_db.ps1` rồi mục 1 bước 3 |
| Mọi API trả `401` | Token cũ: chạy lại `scripts/issue_demo_tokens.py` với `DB_NAME=RTS_DB_DEMO` |
| Demo POS không mở | Chạy từ thư mục repo: `.\clients\demo-pos\DemoPos\bin\Debug\net8.0-windows\DemoPos.exe`; nếu vẫn lỗi, dùng video |
| Smoke check FAIL một bước | Không sửa trên sân khấu; ghi lại mã lỗi, chuyển bước tiếp theo, mở GitHub Issue sau buổi |

## 5. Sau buổi demo

Giữ `RTS_DB_DEMO` để chạy lại; muốn dọn hoàn toàn thì xóa database đó trong SQL Server. Không
dùng `docker compose down -v` trần, vì lệnh đó xóa cả volume phát triển `retailsync_sqlserver_data`.

## 6. Liên kết

- Thiết kế API: `docs/design/openapi.yaml` (DS-04).
- Quy trình test: `docs/design/DS-09_Test_Strategy_and_Simulator.md`.
- Script reset: `scripts/demo/reset_demo_db.ps1`.
- Smoke check: `scripts/demo/sprint2_smoke.py`.
- Ứng dụng POS: `clients/demo-pos/`.
