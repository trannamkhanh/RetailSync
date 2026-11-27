# Review kết quả kiểm thử lại — Sprint 2 + Sprint 3

> **Bản lưu lịch sử — 26/11/2026, trên `a82b90c`.** Nội dung dưới đây giữ nguyên trạng thái ngày 26/11 để làm bằng chứng cho vòng review đó; nó **không** phản ánh trạng thái hiện tại của repo. Hai điểm đã thay đổi từ đó:
>
> - **Issue #88 đã sửa và đóng** qua PR #89 (`7a04ecb`, merge 26/11 18:28). Vì vậy mọi câu "issue #88 đang open" trong file này là trạng thái lịch sử.
> - Workbook test case và các ảnh `evidence/*.png` nằm ngoài repo, không có trong cây này. Các đường dẫn `evidence/…` là nơi bằng chứng được lưu lúc đó, không phải file đọc được từ repo.

**Người review:** Quang · **Review lần 2:** 26/11/2026 (lần 1: 25/11) · **Code đối chiếu:** main `a82b90c`
**Nguồn dữ liệu:** bản export Google Sheet test case lúc 06:29 26/11 (workbook chia sẻ nội bộ, không đăng kèm repo)
**Phạm vi:** chỉ Sprint 2 và Sprint 3. PB-38 (4 case) và PB-44 (3 case) là việc Sprint 4 — không tính.

## 1. Kết luận

**Đạt.** Ba lỗi nêu ở lần review 25/11 đã được sửa xong và có bằng chứng. Còn **một điểm cần Kiệt xác nhận**: tính độc lập của 28 case thuộc PB-08 / PB-12 / PB-14 / PB-26.

## 2. Việc đã sửa so với lần 1

| Lỗi lần 1 | Trạng thái 26/11 | Bằng chứng |
|---|---|---|
| `DSH50-10` FAIL không có GitHub Issue | **Đã sửa** | Issue [#88](https://github.com/trannamkhanh/RetailSync/issues/88) `[TestCase] DSH50-10: Demo POS loses active discount after offline restart`, mở 25/11 15:13 bởi Sang, **nay đã đóng** (26/11 11:28) bằng PR #89 (`7a04ecb`); ô ghi chú của case đã có `GitHub issue #88` |
| 12 ô cột K, L của PB-50 bị điền `SKIPPED` | **Đã sửa** | Cả 12 dòng PB-50 nay để trống K và L; dòng `Re-test Status` của PB-50 = 12 / 0 / 0 / 0 / 0 |
| 5 case SKIPPED không ghi lý do | **Đã sửa** (ghi lý do) | `POS45-1`…`POS45-4` và `STF47-1` đều có lý do; `DSH50-11` cũng có lý do |

Nhờ vậy số liệu re-test đã đúng: **Sprint 3 re-test skipped = 5** (lần 1 là 17), toàn bộ 43 sheet **5 skipped** (lần 1 là 17).

**Cập nhật cuối ngày 26/11 — 5 case SKIPPED đã kiểm thử lại và PASS.** `POS45-1`, `POS45-2`, `POS45-3`, `POS45-4` và `STF47-1` đã được chạy lại bằng GUI thật trên stack demo `RTS_DB_DEMO` tại main `a82b90c`; cả 5 đạt, ảnh bằng chứng ở `evidence/<case_id>.png`. Chi tiết: `Retest_Skipped_Cases.md`. Năm case này **cần được đổi từ `SKIPPED` sang `PASS` kèm ngày ở cột L** trên Google Sheet; sau khi đổi, số re-test skipped còn lại là **0** (ngoài PB-50 vốn không dùng cột L) và tổng vòng này thành **260 PASS, 1 FAIL, 1 SKIPPED, 0 Not Implemented**.

**Và `DSH50-11` (PB-50) cũng đã kiểm lại và PASS** — hộp Giảm giá của Staff App khớp API ở cả hai phạm vi, marker "Đã bán giá giảm" đổi đúng sau khi bán, hộp chỉ đọc. Case này ghi vào cột **J** của PB-50 (không dùng cột L). Sau khi sửa cả 6 case, PB-50 chỉ còn **1 FAIL** (`DSH50-10`, issue #88 — sửa xong qua PR #89) và **không còn SKIPPED** nào trên toàn bộ workbook.

## 3. Số liệu đã xác nhận (26/11)

| Người | Được giao | Đã điền | Kết quả |
|---|---|---|---|
| Khánh | 129 case re-test | 129/129 (cột K có ngày) | 129 PASS |
| Sang | 121 case re-test + 12 case PB-50 (lần đầu) | 121/121 + 12/12 | re-test: 116 PASS, 5 SKIPPED · PB-50: 10 PASS, 1 FAIL, 1 SKIPPED |
| Không thuộc vòng này | 7 (PB-38, PB-44) | — | Not Implemented — việc Sprint 4 |

Tổng vòng này **262 case**: **255 PASS, 1 FAIL, 6 SKIPPED, 0 Not Implemented**.

Kiểm tự động trên 269 case: khớp đủ `Test_Case_Mapping.csv`; 250 case re-test đều có ngày cột K đúng định dạng; cột L chỉ có PASS / SKIPPED; **0 FAIL ở cột L**.

Theo backlog: **Sprint 2 = 87 case**, **Sprint 3 = 167 case**. PB-37 (8 case) backlog xếp Sprint 4 nhưng đã re-test xong 8/8 PASS.

## 4. Điểm còn mở

### 4.1. 28 case do chính người viết code re-test (cần Kiệt xác nhận)

Bốn tab trong danh sách của Khánh có code chính do `trannamkhanh` viết:

| Tab | Số case | Bằng chứng Git |
|---|---|---|
| PB-08 Store and POS Registry | 8 | `b3550d2` 01/11 *"feat: add store and POS terminal registration API (PB-08-1)"*, `d00e4c3`, `d8a7d21`, `a31e357` — 15 file do Khánh tạo |
| PB-12 Stock Query | 6 | `e88502b` 02/11 *"feat: add the store inventory query API (PB-12-1, PB-12-2, PB-12-3)"*, `ccbfbee` — 10 file |
| PB-14 Sales Aggregation | 7 | `9d83049` 09/11 *"feat(PB-14): aggregate a store's sales into one sync batch"*, `483f35f`, `c8aadff` — 8 file |
| PB-26 Guardrail Configuration | 7 | `556591e` 05/11 *"feat: add the guardrail rule admin API (PB-26-1, PB-26-2, PB-26-3)"* — 11 file |

Sheet không ghi ai điền cột K/L và ô ghi chú của 4 tab vẫn chỉ có tên người phụ trách tab. Vì vậy **không kiểm được** đã đổi người theo Mục 7 hay chưa.
**Cần:** Khánh báo Kiệt đổi người cho 4 tab, hoặc Kiệt xác nhận 28 case này được chấp nhận.

### 4.2. `DSH50-10` vẫn FAIL — theo dõi ở PB-41

Case này FAIL thật (Test Date 24/11) và issue #88 mở ra để sửa; **nay đã đóng bằng PR #89 (`7a04ecb`)**. Với bản lưu 26/11 thì đây không còn là lỗi của vòng test, và khi báo cáo phải nói đúng thứ tự: **PB-50 từng có 1 FAIL, đã sửa trong PB-41, workbook cần Sang cập nhật lại ô của `DSH50-10`**.

### 4.3. Lưu ý về công cụ

`cross_test_totals.py` in dòng cuối **"No failed cases."** vì với mỗi sheet nó chỉ lấy **một** dòng đếm: dòng `Re-test Status` nếu sheet có dòng đó, ngược lại mới rơi về dòng `Status` (`scripts/metrics/cross_test_totals.py`, hàm `failed_sheets`). PB-50 **có** dòng `Re-test Status` nhưng để trống cột L, nên dòng đó đếm 0 fail và FAIL của `DSH50-10` ở dòng `Status` bị che — chi tiết vẫn có ở dòng `PB-50 ... 10 pass, 1 fail ... of 12`. Khi đưa totals cho Kiệt, phải nêu FAIL này bằng lời, không chỉ dựa vào dòng kết luận của script.

## 5. Totals để đưa Kiệt (bản 26/11)

Số dưới đây là trạng thái **trên Sheet lúc 06:29 26/11** (5 case còn `SKIPPED`):

```
Sprint 2: 87 pass, 0 fail, 0 not implemented, 0 skipped / 87
          Re-test Status: 87 pass, 0 fail, 0 not implemented, 0 skipped / 87
Sprint 3: 165 pass, 1 fail, 0 not implemented, 1 skipped / 167
          Re-test Status: 150 pass, 0 fail, 0 not implemented, 5 skipped / 167
Toàn bộ 43 sheet — Re-test Status: 245 pass, 0 fail, 0 not implemented, 5 skipped / 269
```

Sau khi Sheet được cập nhật 5 case đã kiểm lại thành `PASS`, số sẽ là **250 pass, 0 skip / 269** ở dòng Re-test Status, và Sprint 3 Re-test thành **155 pass, 0 skipped / 167**. Nên chạy lại script sau khi Sheet sửa thay vì chép tay con số dự kiến.

## 6. Xong khi

- [x] PB-50: xoá 12 ô cột K, L — đã xong.
- [x] `DSH50-10` có GitHub Issue — issue #88, nay đã đóng bằng PR #89 (`7a04ecb`).
- [x] 5 case SKIPPED có lý do — đã xong.
- [x] 5 case SKIPPED (`POS45-1`…`POS45-4`, `STF47-1`) kiểm thử lại — **5/5 PASS**, xem `Retest_Skipped_Cases.md`.
- [x] `DSH50-11` (PB-50) kiểm thử lại — **PASS**, xem mục 2.6 của `Retest_Skipped_Cases.md`.
- [ ] Khánh/Sang đổi 5 case ở cột L và `DSH50-11` ở cột J từ `SKIPPED` sang `PASS` trên Google Sheet.
- [ ] Kiệt xác nhận việc đổi người cho 28 case của PB-08 / PB-12 / PB-14 / PB-26.
- [ ] Đưa Kiệt totals kèm ghi chú lịch sử về 1 FAIL của PB-50 (issue #88, đã đóng).
- [ ] Đánh Done TC-KH và TC-SA trên Sprint Backlog.

## 7. Phụ lục — cách kiểm

- Bản export Google Sheet tải 06:29 26/11, đọc bằng `openpyxl` (giá trị cache của công thức).
- Đối chiếu từng case với `Test_Case_Mapping.csv` (269 case): cột ghi, người được giao, giá trị kết quả, định dạng ngày, ô ghi chú.
- `python scripts/metrics/cross_test_totals.py --cases <export.xlsx> --backlog "C1SE_24_RetailSync_Sprint_Backlog_v1.4.xlsx"`, exit 0.
- Bằng chứng tác giả code: `git log --all --no-merges --format='%h|%an|%ad|%s' --date=short --name-only` chạy trong checkout của repo; tab quy theo mã PB trong subject commit, rồi lấy file mà commit đó tạo lần đầu. Giới hạn: commit không ghi mã tab vẫn có thể lọt.
- Kiểm GitHub Issue qua API: [search DSH50](https://api.github.com/search/issues?q=repo:trannamkhanh/RetailSync+DSH50) trả `total_count: 1` (issue #88), lúc viết là open, **nay state = closed**.
