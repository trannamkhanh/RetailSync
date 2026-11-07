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

# 4. Chạy smoke check, phải PASS toàn bộ
docker compose run --rm --volume "${PWD}:/repo" --workdir /repo middleware python scripts/demo/sprint2_smoke.py
```

Chạy smoke check **hai lần liên tiếp** trên cùng database: cả hai lần đều phải kết thúc bằng
`ALL CHECKS PASSED`. Đây là bằng chứng kịch bản chạy lại được, không phụ thuộc dữ liệu cũ.

Mở sẵn trước khi bắt đầu:

- `clients/demo-pos/DemoPos/bin/Debug/net8.0-windows/DemoPos.exe` (máy POS).
- Một cửa sổ PowerShell tại thư mục gốc repo (để chạy lệnh API).
- Sprint Backlog và file kết quả test case.
- Video diễn tập (dự phòng khi máy hoặc mạng lỗi).

Kiểm tra nhanh cuối cùng:

```powershell
docker compose ps
curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://127.0.0.1:8443/api/v1/health
```

## 2. Mười bốn bước demo

Thời lượng gợi ý 12–15 phút. Cột "Chứng minh" ghi backlog và mã test case trong
`GROUP_08_Test case.xlsx`; case phụ thuộc Sprint 3 trở đi (ví dụ lô hàng) ghi `Not Implemented`
trong báo cáo, không demo.

| # | Người | Thao tác | Kết quả mong đợi | Chứng minh |
|---|---|---|---|---|
| 1 | Kiệt | `curl.exe --ssl-no-revoke --cacert .certs/ca.crt https://localhost:8443/api/v1/health` | `200 {"status":"ok"}` | PB-02-1 |
| 2 | Kiệt | Gọi `/stores/STORE-DN1/inventory` không token, rồi gọi `/admin/guardrail-rules` bằng token Staff | `401 UNAUTHORIZED`, `403 FORBIDDEN` | PS02-1, PS02-4, PS02-7 |
| 3 | Khánh | Dùng token Admin đăng ký store `DM-DEMO` rồi terminal `DM-POS-DEMO`; gửi lại store đó | `201`, `201`, rồi `409 ALREADY_EXISTS` | PB-08 |
| 4 | Quang | Trên Demo POS: chọn `POS-DN1-01`, bán 2 × `SKU-0001`, bấm **Pay (F9)** | `200 OK`, tồn `40 → 38` | PB-05, INV10-1, INV10-2 |
| 5 | Sang | Bấm **Pay** lần nữa với cùng giao dịch (hoặc gửi lại cùng JSON) | `200 DUPLICATE_IGNORED`, tồn vẫn 38 | PB-09, POS09-1, POS09-2 |
| 6 | Sang | Gửi cùng `transaction_id` nhưng đổi số lượng | `409 CONFLICT`, không đổi tồn | PB-09, POS09-3 |
| 7 | Quang | Bán 999 × `SKU-0001` | `409 INSUFFICIENT_STOCK`, tồn không đổi | PB-10, INV10-3 |
| 8 | Quang / Sang | Trả 1 × `SKU-0001` của đơn A; sau đó bán 3 × `SKU-0002` rồi hủy đơn B | Return `200`, tồn `38 → 39`; hủy `200`, `SKU-0002` về đúng số cũ | PB-06 POS06-1; PB-07 POS07-1 |
| 9 | Sang | Hủy đơn A (đã có return) | `409 SALE_HAS_RETURNS` | PB-07, POS07-5 |
| 10 | Khánh | Staff `staff_dn1` đọc tồn `STORE-DN1`, rồi đọc `STORE-DN2` | `200` (9 SKU), rồi `403 FORBIDDEN` | PB-12, INV12-1, INV12-3 |
| 11 | Sang | Tra barcode `8930000000011` | `200`, `SKU-0001 Fresh milk 1L`, tồn 39 | PB-31, STF31-1 |
| 12 | Khánh | Admin đặt `MAX_DISCOUNT` = 150, rồi 40, rồi trả lại 50 | `422` nêu `threshold`; `200` threshold 40; `200` threshold 50 | PB-26, REC26-2, REC26-3 |
| 13 | Kiệt | Gửi POS event không kèm client certificate; sau đó dùng certificate `POS-DN2-01` cho event của `POS-DN1-01` | Gateway trả `400`; middleware trả `403 FORBIDDEN` | PB-48, PS48-5, PS48-6 |
| 14 | Kiệt | Auditor đọc `/audit-logs`, lọc các bản ghi của lần chạy này; Staff đọc audit | `200`, thấy `STOCK_CHANGE`, `DUPLICATE_EVENT`, `EVENT_REJECTED`, `STORE_REGISTERED`, `POS_REGISTERED`, `GUARDRAIL_RULE_UPDATED`; Staff `403` | PB-04, PS04-1, PS04-3, PS04-4, PS04-6 |

Ghi chú khi trình bày:

- Bước 4 là bước duy nhất phải bấm trên giao diện Demo POS; các bước còn lại có thể chạy bằng
  PowerShell để giữ nhịp.
- Nếu bước 5/6 chạy bằng lệnh, dùng lại đúng JSON của bước 4 cho bước 5, và đổi `quantity`
  cho bước 6.
- Bước 12 phải trả `MAX_DISCOUNT` về **50** trước khi sang bước 13; smoke check tự làm việc này.

## 3. Bản rút gọn 7 bước (khi thiếu thời gian)

Nếu buổi báo cáo bị chậm, bỏ các bước 1, 2, 3, 6, 9, 11, 12 và chỉ giữ:

| # | Nội dung | Người |
|---|---|---|
| 4 | SALE qua gateway, tồn 40 → 38 | Quang |
| 5 | Gửi lại, DUPLICATE | Sang |
| 7 | Bán vượt tồn, INSUFFICIENT_STOCK | Quang |
| 8 | RETURN và CANCELLATION | Quang / Sang |
| 10 | Tồn kho giới hạn theo store | Khánh |
| 13 | mTLS: không cert 400, sai cert 403 | Kiệt |
| 14 | Audit log đủ hành động | Kiệt |

## 4. Khi có sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Mất mạng hoặc Docker Desktop dừng | Chuyển sang video diễn tập, giữ phần thuyết trình |
| `/health` không trả lời | `docker compose ps`; nếu service dừng: `docker compose up -d --wait sqlserver middleware pos-gateway` |
| POS trả `403 FORBIDDEN` | Database demo chưa đăng ký fingerprint: chạy lại `reset_demo_db.ps1` rồi bước 3 ở mục 1 |
| Mọi API trả `401` | Token cũ: chạy lại `scripts/issue_demo_tokens.py` với `DB_NAME=RTS_DB_DEMO` |
| Demo POS không mở | Chạy bằng PowerShell từ thư mục repo: `.\clients\demo-pos\DemoPos\bin\Debug\net8.0-windows\DemoPos.exe`; nếu vẫn lỗi, dùng video |
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
