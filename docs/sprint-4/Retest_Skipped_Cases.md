# Kiểm thử lại các case bị SKIPPED — kết quả

> **Bản lưu lịch sử — 26/11/2026, trên `a82b90c`.** File giữ nguyên trạng thái ngày 26/11 để làm bằng chứng cho vòng kiểm thử đó; nó **không** phản ánh trạng thái hiện tại của repo. Ba điểm cần biết trước khi đọc:
>
> - **`scripts/demo/run_client_tests.ps1`, `capture_window.ps1` và `drive_ui.ps1` không có trong repo.** Đó là các script phụ chỉ tồn tại trên máy chạy lần kiểm. Trong repo chỉ có `scripts/demo/run_console_tests.ps1`, và nó chỉ phủ demo console — nên hai dòng `DemoPos.Tests` / `StaffApp.Tests` **không tái lập được chỉ từ repo** (`Regression_Evidence_v1.0.md` §6).
> - **Các file `evidence/*.png` và `evidence/_tests-*.txt` không có trong repo.** Đường dẫn là nơi bằng chứng được lưu lúc đó trên máy cá nhân.
> - **Issue #88 đã sửa và đóng** qua PR #89 (`7a04ecb`, merge 26/11 18:28). Dòng "issue #88 đang open" ở §5.2 là trạng thái lịch sử.

**Người kiểm:** Quang · **Ngày:** 26/11/2026 · **Code:** main `a82b90c` (worktree sạch `a82b90c`, HEAD xác nhận)
**Môi trường:** stack demo riêng, project `retailsync-test`, DB `RTS_DB_DEMO`; `RTS_DB` và stack dev không bị chạm.
**Kết quả:** **6/6 PASS** — 5 case SKIPPED của vòng re-test Sprint 2+3, cộng `DSH50-11` của PB-50 (lần kiểm bổ sung, xem mục 2.6).

## 1. Tổng hợp

| Case | Nội dung | Trước | Nay | Bằng chứng |
|---|---|---|---|---|
| POS45-1 | 6 terminal, mỗi máy có store_id và pos_id riêng | SKIPPED | **PASS** | `evidence/POS45-1.png` |
| POS45-2 | Bán hàng trên UI, tồn kho hiển thị đúng | SKIPPED | **PASS** | `evidence/POS45-2.png` |
| POS45-3 | Phản hồi khi giao dịch trùng | SKIPPED | **PASS** | `evidence/POS45-3.png` |
| POS45-4 | Phản hồi khi giao dịch bị từ chối | SKIPPED | **PASS** | `evidence/POS45-4.png` |
| STF47-1 | Danh sách đề xuất chỉ hiện PENDING | SKIPPED | **PASS** | `evidence/STF47-1.png` + `evidence/_tests-staffapp.txt` |
| **DSH50-11** | **Hộp Giảm giá của Staff App, đổi Cửa hàng của tôi / Tất cả cửa hàng** | SKIPPED | **PASS** | `evidence/DSH50-11.png`, `evidence/DSH50-11-all.png` |

Bộ test của hai client trên đúng commit, chạy lại toàn bộ:
- `DemoPos.Tests`: **101 passed, 0 failed, 0 skipped**
- `StaffApp.Tests`: **84 passed, 0 failed, 0 skipped**

## 2. Chi tiết từng case

### POS45-1 — Six terminals are available (PASS)

Bước: mở Demo POS, tab **Terminals**.

Kết quả thực tế: dòng tiêu đề "6 máy POS đã cấu hình", bảng có đúng 6 dòng, mỗi dòng một cặp (Store, POS id) khác nhau:

| Store | POS id | Cert | Key |
|---|---|---|---|
| Cửa hàng Hải Châu | POS-DN1-01 | OK | OK |
| Cửa hàng Hải Châu | POS-DN1-02 | OK | OK |
| Cửa hàng Thanh Khê | POS-DN2-01 | OK | OK |
| Cửa hàng Thanh Khê | POS-DN2-02 | OK | OK |
| Cửa hàng Sơn Trà | POS-DN3-01 | OK | OK |
| Cửa hàng Sơn Trà | POS-DN3-02 | OK | OK |

Khớp seed `database/seed/001_demo_stores_pos.sql` (3 cửa hàng × 2 POS). Fingerprint hiển thị 12 ký tự đầu SHA-256 (DER), khớp giá trị đăng ký trong `pos_terminal`.

### POS45-2 — Live sale UI and stock display (PASS)

Bước: chọn terminal **Cửa hàng Hải Châu · POS-DN1-01** → thêm `SKU-0001` (Fresh milk 1L) → **Pay · gửi SALE (F9)**.

Kết quả thực tế một lần bán:
- Giỏ hàng: `SKU-0001` × 1, giá gốc 32.000, thành tiền 32.000, tổng "32,000 đ · 1 món".
- Sau khi Pay: khung kết quả xanh **OK / OK / Event applied**, `current_stock: SKU-0001=39`, 204 ms · HTTP 200.
- Lịch sử terminal thêm dòng SALE `TXN-POS-DN1-01-20261126005310-0884`, Kết quả `OK`, Code `OK`.
- Tồn kho trước khi bán là 40 (seed), sau khi bán là 39 — đúng nghiệp vụ.

### POS45-3 — Duplicate-sale feedback (PASS)

Bước: chọn dòng SALE vừa bán → **Send again (cùng transaction_id)**.

Kết quả thực tế:
- Khung kết quả xanh dương **DUPLICATE / DUPLICATE_IGNORED / Transaction already recorded**, 58 ms · HTTP 200.
- `current_stock: SKU-0001=39` — **không đổi**, không trừ kho lần hai.
- Lịch sử có thêm dòng cùng Transaction id `TXN-POS-DN1-01-20261126005310-0884`, Kết quả `DUPLICATE`, Code `DUPLICATE_IGNORED`.

### POS45-4 — Rejected-sale feedback (PASS)

Chuẩn bị: đặt `quantity = 0` cho `SKU-0003` của `STORE-DN1` trong `RTS_DB_DEMO` để tạo ca bị từ chối.

Bước: chọn `SKU-0003` (Cheese slices 200g, 65.000) → thêm vào giỏ → **Pay**.

Kết quả thực tế:
- Khung kết quả đỏ **REJECTED / INSUFFICIENT_STOCK / "Not enough stock for SKU-0003 at store STORE-DN1"**, 86 ms · **HTTP 409**.
- Lịch sử thêm dòng `TXN-POS-DN1-01-20261126005815-5838`, Kết quả `REJECTED`, Code `INSUFFICIENT_STOCK`.
- Giỏ hàng được xoá sau khi bị từ chối; tồn kho `SKU-0003` vẫn 0 (không bị trừ sai).

Dữ liệu demo đã được khôi phục: `SKU-0003` về 40, các recommendation đã đổi trạng thái về `PENDING`.

### STF47-1 — The list shows pending only (PASS)

Chuẩn bị: `RTS_DB_DEMO` có 6 recommendation `PENDING` cho `STORE-DN1` (rec_id 1–6: SKU-0001, 0002, 0003, 0007, 0008, 0009). Đặt `rec_id=1` thành `ACCEPTED`, `rec_id=2` thành `REJECTED` để có dữ liệu đối chứng.

Bước: mở Staff App với token `staff_dn1` (STORE-DN1) → tab **Đề xuất**.

Kết quả thực tế: danh sách có **đúng 4 dòng** — SKU-0003, SKU-0007, SKU-0008, SKU-0009, tất cả "Giảm giá 30%". Hai SKU đã quyết định (**SKU-0001** ACCEPTED, **SKU-0002** REJECTED) **không xuất hiện**. Panel chi tiết hiện "Chọn một đề xuất" khi chưa chọn dòng. Trạng thái "Đã tải đề xuất."

Đối chứng máy kiểm: `RecommendationBoardTests` và `ApiParsersTests` (nhánh `items` chỉ chứa PENDING) — 84/84 test của `StaffApp.Tests` pass, gồm cả `RecommendationBoardTests`.

### 2.6. DSH50-11 — The Staff App Discounts box (PASS)

Case này nằm ở PB-50 nên ghi kết quả vào cột J, không dùng cột L.

Chuẩn bị: chấp nhận 2 recommendation `DISCOUNT` để tạo giảm giá đang hiệu lực — `rec_id=1` (STORE-DN1, SKU-0001, 30%) bằng token `staff_dn1`, `rec_id=7` (STORE-DN2, SKU-0001, 30%) bằng token `staff_dn2`. Giá gốc 32.000, giá sau giảm 22.400.

Đối chứng API (cùng token `staff_dn1`):

| Gọi | Kết quả |
|---|---|
| `GET /staff/discounts?scope=own` | 1 dòng: STORE-DN1, SKU-0001, 30%, 22.400, `sold_at_discount=false` |
| `GET /staff/discounts?scope=all` | 2 dòng: STORE-DN1 (bỏ trống khoảng cách) và STORE-DN2 (4.42 km), cùng `sold_at_discount=false` |

Kết quả trên UI:

1. Tab **Giảm giá**, chọn **Cửa hàng của tôi**: 1 dòng — "Cửa hàng Hải Châu (tôi)", Fresh milk 1L (SKU-0001), lô `B-STORE-DN1-SKU-0001-1`, HSD 29/11/2026, Giảm 30%, Giá **22,400 VND**, Từ lúc 26/11 08:16, "Đã bán giá giảm" = Chưa. **Khớp đúng** `scope=own`.
2. Chọn **Tất cả cửa hàng**: 2 dòng — thêm "Cửa hàng Thanh Khê", khoảng cách **4.42 km**, cùng SKU/lô/giảm giá. **Khớp đúng** `scope=all`, đúng thứ tự (cửa hàng mình trước, rồi theo khoảng cách).
3. Bán `SKU-0001` trên Demo POS (giá đơn vị 22.400 — POS đã nhận bảng giảm giá, trạng thái "Giảm giá: 1 mã"), rồi bấm **Làm mới** trên Staff App: cột "Đã bán giá giảm" của STORE-DN1 chuyển thành **Có**, STORE-DN2 vẫn **Chưa**. API trả `sold_at_discount: True` cho DN1 và `False` cho DN2 — **khớp**.
4. Hộp là **chỉ đọc**: `MainForm.cs` dựng grid bằng `Grid(...)` với `ReadOnly = true`, `AllowUserToAddRows = false`, `AllowUserToDeleteRows = false`.

Vậy cả 4 điểm của Expected Result đều đạt: cùng các dòng như API, chỉ đọc, có marker "đã bán giá giảm", và đổi được giữa hai phạm vi.

## 3. Cách dựng môi trường (để tái lập)

```powershell
# Worktree sạch tại đúng commit
git worktree add <path> a82b90c

# .env, .tokens và .certs/ lấy từ checkout đang dùng (certs phải còn hạn và khớp DB)

# Stack riêng, không dùng chung với stack dev
docker compose -p retailsync-test up -d --build sqlserver
docker compose -p retailsync-test run --rm --no-deps migrate
docker compose -p retailsync-test up -d middleware hq-demo pos-gateway

# Đăng ký fingerprint chứng chỉ POS vào pos_terminal
docker compose -p retailsync-test run --rm --no-deps --volume "${PWD}:/repo:ro" \
  --workdir /repo middleware python scripts/register_pos_certificates.py
```

Middleware healthy: `{"status":"ok"}` trên `https://127.0.0.1:8443/api/v1/health`.

Build và chạy client:
```powershell
dotnet build clients/demo-pos/DemoPos.sln -c Debug
dotnet build clients/staff-app/StaffApp.sln -c Debug
```
Staff App cần `ca.crt` cạnh file thực thi và `staff_token.txt` chứa token `staff_dn1`.

Bộ test (dùng xunit console runner, vì `dotnet test` hỏng trên host này — xem mục 4). Hai script dưới đây **không có trong repo**; chúng chỉ tồn tại trên máy chạy lần kiểm 26/11:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_client_tests.ps1 -Client demo-pos
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_client_tests.ps1 -Client staff-app
```
Cách tái lập thay thế, chỉ dùng thứ có trong repo: build solution rồi chạy xunit console runner trực tiếp, đúng kỹ thuật mà `scripts/demo/run_console_tests.ps1` dùng cho demo console (copy runner vào thư mục test bin, viết `xunit.console.runtimeconfig.json` cho `Microsoft.WindowsDesktop.App`, copy `Microsoft.Data.SqlClient.dll` và `SNI.dll` theo RID). Chi tiết từng bước ở `Regression_Evidence_v1.0.md` §6.

## 4. Ghi chú kỹ thuật gặp trong lúc kiểm

1. **App phải chạy từ đường dẫn trên ổ C.** Bản build đặt trong worktree trên một ổ khác `C:` mở ra thì thoát ngay với `UnauthorizedAccessException` khi tạo thư mục `%LOCALAPPDATA%\RetailSync\DemoPos`, dù tài khoản có toàn quyền trên thư mục đó. Chép cùng bộ file sang `%TEMP%` (ổ C) thì chạy bình thường và LIVE. Đây là hạn chế môi trường, không phải lỗi sản phẩm.
2. **`dotnet test` không dùng được trên host này**: testhost thoát với `Win32Exception (5): Access is denied` khi mở handle tới tiến trình cha. Repo đã có sẵn `scripts/demo/run_console_tests.ps1` cho đúng tình huống này; lúc kiểm tôi dùng thêm một script phụ `run_client_tests.ps1` cho `demo-pos` và `staff-app` — **script đó không được commit vào repo**. Không sửa code sản phẩm.
3. Script phụ trợ dùng để chụp bằng chứng (**không có trong repo**): `capture_window.ps1` (PrintWindow, chụp đúng cửa sổ kể cả khi bị che) và `drive_ui.ps1` (đưa cửa sổ lên trước, click theo toạ độ, gõ phím).

## 5. Giới hạn của lần kiểm này

- Ảnh là bằng chứng màn hình của một lần chạy thật trên `RTS_DB_DEMO`; không phải ảnh dựng lại.
- POS45-2 chỉ kiểm một lần bán một SKU; các trường hợp nhiều dòng, số lượng > 1 do bộ test tự động phủ.
- POS45-4 tạo tình huống hết tồn kho bằng cách sửa dữ liệu demo, không qua nghiệp vụ bán hết hàng. Lý do: seed đặt 40 đơn vị mỗi SKU, bán hết sẽ phải 40 lần thao tác. Dữ liệu đã khôi phục sau khi kiểm.
- Chữ ký chứng chỉ và kết nối mTLS dùng CA dev trong `.certs/`, không phải CA thật.
- Các case trong Sheet vẫn cần Khánh/Sang đổi `SKIPPED` → `PASS` ở cột L (và ghi ngày) — việc này tôi không tự sửa Sheet. Riêng `DSH50-11` thuộc PB-50 nên ghi vào cột **J**, không phải cột L.
- DSH50-11 chỉ kiểm với hai cửa hàng có giảm giá đang hiệu lực (STORE-DN1 và STORE-DN2). Trường hợp không có giảm giá nào (danh sách rỗng) do test `DiscountsTests` phủ, không kiểm bằng mắt lần này.

## 6. Tệp bằng chứng

Các file dưới đây **không nằm trong repo** (xem banner đầu file); đường dẫn là nơi lưu lúc kiểm 26/11.

| Tệp | Nội dung |
|---|---|
| `evidence/POS45-1.png` | Tab Terminals: 6 máy POS, store/pos id riêng, Cert/Key OK |
| `evidence/POS45-2.png` | Sau khi Pay: OK, HTTP 200, current_stock SKU-0001=39 |
| `evidence/POS45-3.png` | Send again: DUPLICATE / DUPLICATE_IGNORED, kho không đổi |
| `evidence/POS45-4.png` | Pay với tồn 0: REJECTED / INSUFFICIENT_STOCK, HTTP 409 |
| `evidence/STF47-1.png` | Tab Đề xuất: chỉ 4 dòng PENDING, không có ACCEPTED/REJECTED |
| `evidence/DSH50-11.png` | Tab Giảm giá, "Cửa hàng của tôi": 1 dòng, 22,400 VND, Đã bán giá giảm = Có |
| `evidence/DSH50-11-all.png` | Tab Giảm giá, "Tất cả cửa hàng": 2 dòng, DN2 4.42 km, DN2 = Chưa |
| `evidence/_tests-demopos.txt` | Kết quả `DemoPos.Tests`: 101 passed |
| `evidence/_tests-staffapp.txt` | Kết quả `StaffApp.Tests`: 84 passed |
