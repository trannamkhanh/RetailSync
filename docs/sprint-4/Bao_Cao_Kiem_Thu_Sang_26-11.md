# Kiểm thử sáng 26/11/2026 — báo cáo để trao đổi nhóm

> **Bản lưu lịch sử — 26/11/2026, trên `a82b90c`.** File này giữ nguyên trạng thái ngày 26/11 để làm bằng chứng cho vòng kiểm thử đó; nó **không** phản ánh trạng thái hiện tại của repo. Ba điểm đã thay đổi từ đó:
>
> - **Issue #88 đã sửa và đóng** qua PR #89 (`7a04ecb`, merge 26/11 18:28). Câu "issue #88 đang open" ở §5.2 là trạng thái lịch sử.
> - **`scripts/demo/run_client_tests.ps1` không có trong repo** — script đó chỉ tồn tại trên máy chạy lần kiểm 26/11. Trong repo chỉ có `scripts/demo/run_console_tests.ps1` (chỉ phủ demo console).
> - **Các file `evidence/*.png` và `evidence/_tests-*.txt` không có trong repo.** Đó là nơi bằng chứng được lưu lúc đó trên máy cá nhân, không phải file đọc được từ checkout này.

**Người thực hiện:** Quang · **Code:** main `a82b90c` · **Thời gian:** 07:45 – 08:25, 26/11/2026
**Môi trường:** worktree sạch tại `a82b90c`, stack demo riêng (`docker compose -p retailsync-test`), DB `RTS_DB_DEMO`.
`RTS_DB` và stack dev **không bị chạm**. Đã khôi phục dữ liệu demo sau khi kiểm.

## 1. Tóm tắt trong 5 dòng

1. Kiểm thử lại **6 case đang SKIPPED** — cả 6 **PASS**.
2. 5 case thuộc vòng re-test Sprint 2+3: `POS45-1`, `POS45-2`, `POS45-3`, `POS45-4`, `STF47-1`.
3. 1 case thuộc PB-50 (lần test đầu): `DSH50-11`.
4. Bộ test hai client trên đúng commit: DemoPos **101/101**, StaffApp **84/84**, 0 skipped.
5. Không sửa code sản phẩm. Chỉ thêm script phụ trợ để chạy test và chụp bằng chứng.

## 2. Vì sao phải làm

Trong Sheet, 6 case này là **SKIPPED** với lý do "chưa kiểm bằng mắt trên UI". Đó là 6 case duy nhất còn SKIPPED trong toàn bộ workbook. Nếu để nguyên thì báo cáo không nói được là giao diện đã được xác nhận, và dòng `Re-test Status` vẫn đếm 5 skipped.

## 3. Kết quả chi tiết

### 3.1. POS45-1 — Six terminals are available → **PASS**

Tab **Terminals** của Demo POS hiện đúng 6 dòng, mỗi máy một cặp (store, pos_id) riêng, cột Cert và Key đều OK:

| Store | POS id |
|---|---|
| Cửa hàng Hải Châu | POS-DN1-01 |
| Cửa hàng Hải Châu | POS-DN1-02 |
| Cửa hàng Thanh Khê | POS-DN2-01 |
| Cửa hàng Thanh Khê | POS-DN2-02 |
| Cửa hàng Sơn Trà | POS-DN3-01 |
| Cửa hàng Sơn Trà | POS-DN3-02 |

Khớp seed `database/seed/001_demo_stores_pos.sql` (3 cửa hàng × 2 POS). Fingerprint hiển thị khớp giá trị đã đăng ký trong `pos_terminal`.

### 3.2. POS45-2 — Live sale UI and stock display → **PASS**

Bán `SKU-0001` (Fresh milk 1L, 32.000) trên terminal POS-DN1-01:

- Giỏ hàng hiện đúng SKU, SL 1, giá gốc 32.000, thành tiền 32.000.
- Kết quả sau Pay: **OK / OK / Event applied**, `current_stock: SKU-0001=39`, 204 ms, **HTTP 200**.
- Tồn kho seed là 40 → sau bán là 39. Đúng nghiệp vụ.
- Lịch sử terminal có dòng SALE `TXN-POS-DN1-01-20261126005310-0884`, Kết quả OK.

### 3.3. POS45-3 — Duplicate-sale feedback → **PASS**

Chọn lại dòng SALE vừa bán → **Send again (cùng transaction_id)**:

- Kết quả: **DUPLICATE / DUPLICATE_IGNORED / "Transaction already recorded"**, 58 ms, HTTP 200.
- `current_stock` **vẫn 39** — không trừ kho lần hai. Đây là điểm quan trọng nhất của case.
- Lịch sử có thêm dòng cùng transaction_id với Kết quả DUPLICATE.

### 3.4. POS45-4 — Rejected-sale feedback → **PASS**

Chuẩn bị: đặt `quantity = 0` cho `SKU-0003` của STORE-DN1 trong `RTS_DB_DEMO`. Bán `SKU-0003` (65.000):

- Kết quả: **REJECTED / INSUFFICIENT_STOCK / "Not enough stock for SKU-0003 at store STORE-DN1"**, 86 ms, **HTTP 409**.
- Lịch sử có dòng `TXN-POS-DN1-01-20261126005815-5838` với Kết quả REJECTED.
- Giỏ hàng được xoá sau khi bị từ chối; tồn kho không bị trừ sai.

### 3.5. STF47-1 — The list shows pending only → **PASS**

Chuẩn bị: STORE-DN1 có 6 recommendation PENDING. Đặt `rec_id=1` thành ACCEPTED và `rec_id=2` thành REJECTED để có dữ liệu đối chứng.

Mở Staff App bằng token `staff_dn1` → tab **Đề xuất**:

- Danh sách hiện **đúng 4 dòng**: SKU-0003, SKU-0007, SKU-0008, SKU-0009 (đều Giảm giá 30%).
- **SKU-0001 (ACCEPTED) và SKU-0002 (REJECTED) không xuất hiện.** Đạt đúng yêu cầu "chỉ PENDING".

### 3.6. DSH50-11 — The Staff App Discounts box → **PASS**

Chuẩn bị: chấp nhận `rec_id=1` (STORE-DN1, SKU-0001, 30%) bằng `staff_dn1` và `rec_id=7` (STORE-DN2, SKU-0001, 30%) bằng `staff_dn2`. Giá gốc 32.000 → 22.400.

So sánh UI với API, cùng token `staff_dn1`:

| Kiểm | Kết quả |
|---|---|
| API `scope=own` | 1 dòng: DN1, 30%, 22.400, `sold_at_discount=false` |
| API `scope=all` | 2 dòng: DN1 (khoảng cách trống) + DN2 (4.42 km) |
| UI **Cửa hàng của tôi** | 1 dòng, khớp: lô `B-STORE-DN1-SKU-0001-1`, HSD 29/11/2026, 30%, **22,400 VND**, Từ lúc 26/11 08:16 |
| UI **Tất cả cửa hàng** | 2 dòng, khớp: thêm Thanh Khê **4.42 km**, đúng thứ tự (cửa hàng mình trước) |
| Bán SKU-0001 trên POS rồi Làm mới | DN1 "Đã bán giá giảm" → **Có**; DN2 → **Chưa**. API: `True` / `False` — khớp |
| Chỉ đọc | `MainForm.cs`: `ReadOnly = true`, `AllowUserToAddRows = false`, `AllowUserToDeleteRows = false` |

Cả 4 điểm của Expected Result đều đạt: giống API, chỉ đọc, có marker đã bán giá giảm, đổi được giữa hai phạm vi.

## 4. Bộ test tự động trên cùng commit

| Bộ test | Kết quả |
|---|---|
| `DemoPos.Tests` | **101 passed**, 0 failed, 0 skipped (20.5 s) |
| `StaffApp.Tests` | **84 passed**, 0 failed, 0 skipped (1.6 s) |

Log đầy đủ: `evidence/_tests-demopos.txt`, `evidence/_tests-staffapp.txt` (ảnh/text lưu ngoài repo, xem §8).

## 5. Việc cần nhóm làm — đây là phần cần trao đổi

### 5.1. Cập nhật Google Sheet (Khánh và Sang)

Tôi **không tự sửa Sheet**. Cần sửa 6 ô, ngày 26/11/2026:

| Case | Cột cần sửa | Từ | Thành |
|---|---|---|---|
| POS45-1, POS45-2, POS45-3, POS45-4 | **L** (Re-test Result) | SKIPPED | PASS |
| STF47-1 | **L** (Re-test Result) | SKIPPED | PASS |
| DSH50-11 | **J** (Actual Result), vì PB-50 không dùng cột L | SKIPPED | PASS |

Nên xoá/ghi lại phần ghi chú "SKIPPED: …" để không còn mâu thuẫn với kết quả.

### 5.2. Ảnh hưởng tới số liệu báo cáo

Nếu sửa đủ 6 ô trên thì:

- Toàn workbook **không còn SKIPPED** nào.
- Dòng `Re-test Status` toàn bộ: **250 pass / 0 skip trên 269 case** (hiện là 245 / 5).
- PB-50 còn **1 FAIL** (`DSH50-10`, GitHub issue #88 — **nay đã đóng** qua PR #89) — sửa thuộc PB-41.
- Trạng thái lần đầu (cột J): **261 pass, 1 fail, 7 Not Implemented, 0 skipped**. 7 Not Implemented là PB-38 (4) và PB-44 (3) — việc Sprint 4.

**Lưu ý khi chạy `cross_test_totals.py`:** script in dòng cuối "No failed cases." vì với mỗi sheet nó chỉ lấy **một** dòng đếm — `Re-test Status` nếu có, ngược lại mới dùng `Status` (hàm `failed_sheets`). PB-50 có dòng `Re-test Status` nhưng để trống cột L, nên FAIL của `DSH50-10` ở dòng `Status` bị che. Khi đưa totals cho Kiệt phải nêu bằng lời, đừng chỉ dựa vào dòng kết luận của script.

### 5.3. Việc vẫn treo từ lần review 25/11 (cần Kiệt)

**28 case của PB-08, PB-12, PB-14, PB-26** đã được re-test và ghi PASS, nhưng theo lịch sử Git thì **chính Khánh** viết code chính của 4 tab này. Sheet không ghi ai điền cột K/L nên không kiểm được đã đổi người theo Mục 7 hay chưa. Cần Kiệt xác nhận đổi người, hoặc chấp nhận 28 case này.

Chi tiết và commit hash: mục 4.1 của `Review_Test_Case_Sprint2-3.md`.

## 6. Hai vấn đề môi trường nhóm nên biết

Không phải lỗi sản phẩm, nhưng sẽ gặp lại:

1. **App GUI phải chạy từ đường dẫn trên ổ C.** Bản build đặt trong worktree trên một ổ khác `C:` mở ra là thoát ngay với `UnauthorizedAccessException` khi tạo `%LOCALAPPDATA%\RetailSync\DemoPos`, dù tài khoản có toàn quyền thư mục đó. Chép cùng bộ file sang `%TEMP%` thì chạy LIVE bình thường. Ai để repo ngoài ổ `C:` sẽ gặp lỗi này.
2. **`dotnet test` không chạy được trên máy này**: testhost thoát với `Win32Exception (5): Access is denied` khi mở handle tới tiến trình cha. Repo đã có `scripts/demo/run_console_tests.ps1` cho đúng tình huống; lúc kiểm tôi dùng thêm một script phụ `run_client_tests.ps1` cho `demo-pos` và `staff-app` — **script đó không được commit vào repo**.

## 7. Giới hạn của lần kiểm

- Ảnh là bằng chứng chụp từ cửa sổ thật của lần chạy thật, không phải dựng lại.
- POS45-2 chỉ kiểm một lần bán một SKU; nhiều dòng, số lượng > 1 do bộ test tự động phủ.
- POS45-4 tạo tình huống hết tồn bằng cách sửa dữ liệu demo (seed 40 đơn vị, bán hết sẽ phải 40 thao tác). Dữ liệu đã khôi phục.
- DSH50-11 chỉ kiểm với 2 cửa hàng **có** giảm giá; trường hợp danh sách rỗng do `DiscountsTests` phủ.
- Chứng chỉ dùng CA dev trong `.certs/`, không phải CA thật.
- Toàn bộ kiểm trên `RTS_DB_DEMO`, không kiểm trên dữ liệu thật.

## 8. Tệp bằng chứng

Các file dưới đây **không nằm trong repo** (xem banner đầu file). Chúng ở thư mục `evidence/` trên máy chạy lần kiểm 26/11; đường dẫn giữ nguyên để đối chiếu với báo cáo gửi nhóm.

| Tệp | Nội dung |
|---|---|
| `evidence/POS45-1.png` | Tab Terminals: 6 máy POS, store/pos id riêng, Cert/Key OK |
| `evidence/POS45-2.png` | Sau Pay: OK, HTTP 200, `current_stock: SKU-0001=39` |
| `evidence/POS45-3.png` | Send again: DUPLICATE / DUPLICATE_IGNORED, kho không đổi |
| `evidence/POS45-4.png` | Pay với tồn 0: REJECTED / INSUFFICIENT_STOCK, HTTP 409 |
| `evidence/STF47-1.png` | Tab Đề xuất: chỉ 4 dòng PENDING |
| `evidence/DSH50-11.png` | Tab Giảm giá, "Cửa hàng của tôi": 1 dòng, 22,400 VND, Đã bán = Có |
| `evidence/DSH50-11-all.png` | Tab Giảm giá, "Tất cả cửa hàng": 2 dòng, DN2 4.42 km |
| `evidence/_tests-demopos.txt` | DemoPos.Tests: 101 passed |
| `evidence/_tests-staffapp.txt` | StaffApp.Tests: 84 passed |

Báo cáo chi tiết cùng cách tái lập: `Retest_Skipped_Cases.md`. Số liệu review toàn vòng: `Review_Test_Case_Sprint2-3.md`.
