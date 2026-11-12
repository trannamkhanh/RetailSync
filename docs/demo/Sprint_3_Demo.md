# Kịch bản demo Sprint 3 (báo cáo mentor 14/11/2026)

Runbook cho buổi demo trên 3 máy: **S** chạy stack Docker và bảng điều khiển demo trên máy
chiếu, **A** chạy Demo POS `POS-DN1-01` (Hải Châu), **B** chạy Demo POS `POS-DN2-01`
(Thanh Khê). Mọi bước dùng database demo riêng `RTS_DB_DEMO` và HQ demo `RTS_HQ`, không
bao giờ `RTS_DB`.

Mỗi bước có một nút trên bảng điều khiển (`clients/demo-console/`) và một script dự phòng
trong `scripts/demo/`. Nút và script gọi cùng một API với token đúng vai trò.

## 1. Chuẩn bị máy S

Từ thư mục gốc repo, trong PowerShell. Docker Desktop đã chạy.

### 1.1. Build một lần

```powershell
dotnet build clients/demo-console/DemoConsole.sln
dotnet build clients/demo-pos/DemoPos/DemoPos.csproj
```

### 1.2. `.env` cho buổi demo

Sửa `.env` bằng tay (không commit). In các dòng cần đặt:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -DemoMode
```

Các dòng: `DB_NAME=RTS_DB_DEMO`, `HQ_DB_NAME=RTS_HQ`, `SYNC_INTERVAL=60`,
`SYNC_RETRY_BASE_SECONDS=10`.

Lưu ý: với `SYNC_INTERVAL=60` scheduler tự đồng bộ mỗi phút, nên batch có thể đã ACKED
trước khi bấm **Chạy đồng bộ** ở màn 5. Nếu `/sync/run` đã merge, có thể để
`SYNC_INTERVAL=3600` để nút bấm là thứ tạo batch. Kiệt chốt trước buổi diễn tập.

### 1.3. Chứng chỉ có IP của máy S

Xem mục 3 (Khánh, PB-45-6). Sau khi tạo lại chứng chỉ phải reset lại database để đăng ký
vân tay POS mới.

### 1.4. Reset dữ liệu demo

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1
```

Script dừng `middleware`, `pos-gateway`, `hq-demo`, tạo lại `RTS_DB_DEMO` và `RTS_HQ`,
đăng ký vân tay POS, cấp 13 token vào `.tokens/demo_tokens.json`, nạp 90 ngày lịch sử
(`HIST-`, seed 42), dời hạn vài lô theo ngày nghiệp vụ UTC+7. Khi `.env` có
`DB_NAME=RTS_DB_DEMO`, script khởi động lại ba service và chạy job `forecast` nếu đã có.
Mất khoảng 45 giây.

Kết quả đúng (cuối output):

- Tồn: STORE-DN1 360, STORE-DN2 225, STORE-DN3 135 (9 SKU mỗi cửa hàng, 40/25/15).
- Lô cận hạn ở STORE-DN1 và STORE-DN2: Bread hết hạn sau 1 ngày, Fresh milk 2 ngày,
  Yogurt 3 ngày, Sponge cake **đã hết hạn** từ hôm qua và vẫn còn hàng. STORE-DN3 không
  có lô cận hạn. Các lô sớm khác nằm ngay ngoài ngưỡng (Dairy 6 ngày, Bakery 5 ngày,
  Dry goods 60 ngày).
- `history_transactions` 2320, từ 90 ngày trước đến hôm qua.
- HQ: `hq_batches 0`, `hq_total_rows 0`.
- `Forecast job ran.` hoặc `Forecast skipped: no forecast job on main yet.`

### 1.5. Smoke check

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/demo/sprint2_smoke.py
```

Phải kết thúc bằng `ALL CHECKS PASSED`. Smoke bán và trả hàng ở STORE-DN1, nên **reset lại
lần cuối** (bước 1.4) để demo bắt đầu từ 40/25/15.

### 1.6. Mở bảng điều khiển

```powershell
clients/demo-console/DemoConsole/bin/Debug/net8.0-windows/DemoConsole.exe
```

Cửa sổ mở toàn màn hình, tiêu đề có `(RTS_DB_DEMO)`. Mỗi tab có dòng "Làm mới lúc ...
Không có lỗi." màu xanh. Chữ to hơn cho máy chiếu: tạo
`clients/demo-console/DemoConsole/appsettings.Local.json` với `{ "FontSize": 16 }`.

Nút xám kèm dòng chữ cam nghĩa là tính năng chưa có trên `main` (API trả 404): bảng điều
khiển kiểm tra lại mỗi 30 giây, nên sau khi PR merge và middleware khởi động lại, nút tự
bật. Riêng **Chạy dự báo**: nút tắt sau khi bấm mà nhận 404; mở lại bảng điều khiển sau
khi PB-22/23 merge.

### 1.7. Kiểm tra nhanh trước giờ demo

```powershell
docker compose ps
powershell -ExecutionPolicy Bypass -File scripts/demo/audit_tail.ps1 -Limit 3
powershell -ExecutionPolicy Bypass -File scripts/demo/hq_mode.ps1 -Mode ONLINE
```

## 2. Chuẩn bị máy A và B

- Demo POS: cấu hình địa chỉ máy S, chứng chỉ POS, token theo mục 3 (Khánh).
- Máy A còn chạy script tra cứu liên cửa hàng (màn 6 bước 3): chép `.certs/ca.crt` và
  `.tokens/demo_tokens.json` từ máy S vào cùng chỗ trong repo trên máy A (không commit).
- Mỗi máy bán thử một đơn rồi báo Quang; Quang reset lại (bước 1.4) trước giờ demo.

## 3. Mạng riêng (Khánh, PB-45-6)

Khánh bổ sung trong PR PB-45-6: IP tĩnh máy S, chế độ mạng Private, firewall mở 9443 và
8443, chứng chỉ server có IP máy S, cấu hình Demo POS trên A và B.

## 4. Kịch bản trên bảng điều khiển

Bảng điều khiển luôn chiếu từ máy S. Kết quả mỗi nút (HTTP status, code, thông điệp) hiện ở
dòng dưới cùng. Dòng nào vừa đổi tô vàng 15 giây.

### Màn 2: Bán hàng thời gian thực

| Bước | Ai | Thao tác | Trên bảng điều khiển |
|---|---|---|---|
| 1 | Khánh (A) | Bán 2 × Fresh milk 1L | Tab **Tồn và lô**: dòng STORE-DN1 / SKU-0001 tô vàng, cột Thay đổi `40 → 38`. Bấm vào dòng đó: bảng lô cho thấy lô `-1` (hạn sớm nhất) bị trừ. Tab **Giao dịch và audit**: giao dịch mới và audit `STOCK_CHANGE` |
| 2 | Sang (B) | Bán một giỏ nhiều món | Giao dịch STORE-DN2 xuất hiện cùng chỗ; các dòng STORE-DN2 tô vàng |
| 3 | Khánh và Sang | Bán gần như cùng lúc | Hai giao dịch, tồn mỗi cửa hàng đúng |

Dự phòng: `scripts/demo/audit_tail.ps1 -Action STOCK_CHANGE`, và ảnh chụp tồn chỉ đọc:

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo:ro" --workdir /repo middleware python clients/demo-pos/tools/db_snapshot.py --store STORE-DN1 --watch 2
```

### Màn 3: Tin cậy và bảo mật

Thao tác trên Demo POS như Demo_Plan. Trên tab **Giao dịch và audit**:

| Bước | Thấy gì |
|---|---|
| Gửi lại | Audit `DUPLICATE_EVENT` (chữ cam), tồn không đổi ở tab 1 |
| Conflict (F12) | Không có giao dịch mới, không đổi tồn |
| Sai chứng chỉ (F12) | Audit `EVENT_REJECTED` (chữ đỏ) với `FORBIDDEN` |
| Trả 1 món | Giao dịch `RETURN`; tab 1: tồn cộng lại, bảng lô cho thấy đúng lô đã trừ được cộng lại |
| Hủy đơn | Giao dịch `CANCELLATION`, đơn gốc chuyển `CANCELLED`; đơn đã trả: Demo POS báo 409 `SALE_HAS_RETURNS` |

Dự phòng: `scripts/demo/audit_tail.ps1 -Action DUPLICATE_EVENT`, `-Action EVENT_REJECTED`.

### Màn 4: Mất WAN

Thao tác trên máy B như Demo_Plan (bản tự gửi bù hoặc bản thủ công). Trên bảng điều khiển:
tab **Giao dịch và audit** cho thấy các giao dịch của Thanh Khê đến khi cắm lại dây, mỗi
`transaction_id` đúng một lần; tab **Tồn và lô** cho thấy tồn STORE-DN2 đúng.

### Màn 5: Đồng bộ HQ (tab Đồng bộ và HQ)

| Bước | Nút | Thấy gì | Script dự phòng |
|---|---|---|---|
| 1 | **Chạy đồng bộ** | Dòng kết quả `tạo N batch, gửi N, còn chờ 0`; lưới `sync_batch` có batch ACKED cho mỗi cửa hàng có bán; "Tổng ở HQ" khớp số giao dịch | `scripts/demo/sync_run.ps1` |
| 2 | **OFFLINE**, A và B bán thêm, **Chạy đồng bộ** | Dòng "Chế độ HQ: OFFLINE"; batch mới PENDING, cột Lần thử và Lỗi gần nhất `503 HQ_OFFLINE` | `scripts/demo/hq_mode.ps1 -Mode OFFLINE` rồi `sync_run.ps1` |
| 3 | **ONLINE**, **Chạy đồng bộ** | Batch PENDING thành ACKED theo thứ tự cũ trước, tổng HQ tăng đúng, cột Trùng ở HQ là 0 | `hq_mode.ps1 -Mode ONLINE`, `sync_run.ps1` |
| 4 | **Gửi snapshot** | Dòng kết quả `HTTP 422 SNAPSHOT_REJECTED, đúng như mong đợi`; tab 2 có audit `SNAPSHOT_REJECTED` (chữ đỏ); tab 1 tồn không đổi | `scripts/demo/hq_snapshot.ps1` |

Nếu nút **Chạy đồng bộ** xám (`/sync/run` chưa merge): chờ chu kỳ `SYNC_INTERVAL` (60 giây);
lưới tự cập nhật. HQ demo không có API đọc chế độ hiện tại, nên dòng "Chế độ HQ" là chế độ
bảng điều khiển đặt lần cuối; HQ demo khởi động ở ONLINE.

### Màn 6 rút gọn: Cận hạn, tra cứu, dự báo (tab Job)

| Bước | Ai | Thao tác | Thấy gì | Script dự phòng |
|---|---|---|---|---|
| 1 | Quang | **Chạy kiểm tra cận hạn** | Lưới cảnh báo: mỗi cửa hàng DN1, DN2 có Sponge cake `EXPIRED` (chữ đỏ, đứng đầu), Bread, Fresh milk, Yogurt `NEAR_EXPIRY` | `scripts/demo/run_job.ps1 -Name near-expiry` |
| 2 | Quang | Chọn `Dairy`, `7`, **Đặt ngưỡng**, rồi **Chạy kiểm tra cận hạn** | Thêm cảnh báo Cheese slices ở DN1, DN2 và các lô Dairy ở DN3 (tô vàng) | `scripts/demo/set_threshold.ps1 -Category Dairy -Days 7`, rồi `run_job.ps1 -Name near-expiry` |
| 3 | Khánh (A) | Script tra cứu liên cửa hàng | Bảng các cửa hàng khác, gần nhất trước, có khoảng cách và tồn bán được | `scripts/demo/cross_store.ps1 -Barcode 8930000000011 -Store STORE-DN1 -Token staff_dn1 -BaseUrl https://<IP máy S>:8443/api/v1` |
| 4 | Quang | **Chạy dự báo** | Lưới dự báo: mỗi cửa hàng và SKU có dự báo 7 ngày, SURPLUS (cam), SHORTAGE (đỏ), BALANCED | `scripts/demo/run_job.ps1 -Name forecast` |

Lưu ý cho bước 1 và 2:

- Job `near-expiry` (#43) chạy bù lúc middleware khởi động nếu đã qua giờ chạy trong ngày,
  nên sau reset các cảnh báo thường **đã có sẵn** trước khi bấm. Bấm lại không tạo trùng
  (job chạy lại an toàn). Phần "mới xuất hiện" để người xem thấy là bước 2.
- Hạ ngưỡng không đóng các cảnh báo đang mở (PB-21 giữ cảnh báo đến khi lô bán hết), nên
  bước 2 dùng tăng ngưỡng.
- Bước 3 chạy trên máy A, cần middleware nhận kết nối từ IP máy S (mục 3) và PB-35 đã merge.

## 5. Dự phòng (Demo_Plan mục 7)

| Sự cố | Làm gì |
|---|---|
| Máy A hoặc B không kết nối được | Kiểm tra IP, firewall, chế độ Private; thay bằng laptop thứ tư |
| Mạng router lỗi, hoặc PB-45-6 chưa merge | Chạy cả 2 Demo POS trên máy S (hai cửa sổ); mất WAN bằng `docker compose stop pos-gateway`, nối lại bằng `docker compose start pos-gateway` |
| Docker hoặc SQL Server trên S lỗi | Chiếu video diễn tập tối thứ Sáu |
| Bảng điều khiển lỗi | Các script ở mục 4, `db_snapshot.py` (lệnh ở màn 2), trang `https://localhost:9000/api/v1/demo/batches` |
| Một tab báo lỗi đỏ | Đọc dòng "Lỗi gần nhất": thường là middleware hoặc SQL chưa sẵn sàng; các tab khác vẫn chạy, bảng điều khiển tự thử lại sau 3 giây |
| Hết giờ | Bỏ bước 3 của màn 2, bước 2 và 4 của màn 6 |

Mọi script in một dòng `HTTP <status> code: <code> <body rút gọn>` và thoát 0 khi thành
công (`hq_snapshot.ps1` coi 422 `SNAPSHOT_REJECTED` là thành công). Tham số chung:
`-BaseUrl` (mặc định `https://localhost:8443/api/v1`), `-HqBaseUrl` cho `hq_mode.ps1`
(mặc định `https://localhost:9000/api/v1`), `-TokensPath`, `-CaPath`.

## 6. Sau buổi demo

- Đóng bảng điều khiển và Demo POS.
- Trả `.env` về `DB_NAME=RTS_DB`, `SYNC_INTERVAL=3600`, `SYNC_RETRY_BASE_SECONDS=60`, rồi
  `docker compose up -d --force-recreate --wait middleware pos-gateway hq-demo`.
