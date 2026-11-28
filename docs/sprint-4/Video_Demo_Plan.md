# Kế hoạch quay video demo RetailSync (PB-42-4)

**Ngày quay:** 1/12/2026 · **Code:** tag `v1.0` (commit đã freeze lúc 12:00 30/11) · **Thời lượng:** khoảng 20 phút
**Người:** Kiệt dẫn chuyện · Quang điều khiển máy S, quay và dựng · Khánh máy A (Hải Châu) · Sang máy B (Thanh Khê)
**Sơ đồ chỗ ngồi:** cách chia máy A/B và người ngồi ở trên là **dự kiến**, chốt lại với Kiệt trước ngày quay (1/12), không để tới hôm quay mới đổi.
**Dựa trên:** `docs/Demo_Plan.md` (7 màn), `docs/demo/Sprint_3_Demo.md` (lệnh chi tiết)

---

## Phần A. Kế hoạch từng bước

| Bước | Thời gian | Việc | Ai |
|---|---|---|---|
| A1 | 30/11 tối | Gắn tag `v1.0`, mỗi máy `git fetch --tags` rồi `git checkout v1.0` | Kiệt, cả nhóm |
| A2 | 30/11 tối (còn Internet) | Build mọi thứ trên S, A, B (mục B1, B3) | Quang, Khánh, Sang |
| A3 | 1/12, 8:00 | Dựng router và mạng, kiểm tra A, B gọi được S (B2) | Quang |
| A4 | 8:30 | Reset dữ liệu, smoke check, **reset lại** (B1.4) | Quang |
| A5 | 8:45 | Xuất token, chép sang A và B, mở ứng dụng (B1.5, B3) | Quang, Khánh, Sang |
| A6 | 9:00 | Cài phần mềm quay, quay thử 30 giây trên mỗi máy, nghe lại tiếng (B4) | Quang |
| A7 | 9:15 | Tập nhanh màn 2 và màn 6 một lần (không quay), rồi **reset lại** | Cả nhóm |
| A8 | 9:45 | **Quay** màn 1–7, quay từng màn thành một đoạn riêng (Phần C) | Cả nhóm |
| A9 | 11:00 | Xem lại từng đoạn; đoạn nào lỗi thì quay lại riêng đoạn đó (Phần D) | Quang, Kiệt |
| A10 | Chiều | Dựng video: ghép đoạn, chèn tiêu đề màn, phụ đề số liệu màn 7, xuất MP4 1080p | Quang |
| A11 | Tối | Cả nhóm xem bản dựng; Kiệt duyệt | Kiệt |

Quay theo từng màn, không quay một mạch 20 phút. Hỏng ở màn nào thì chỉ quay lại màn đó. Trước khi quay lại màn 2 hoặc màn 6, phải reset dữ liệu, vì tồn kho và đề xuất đã thay đổi.

---

## Phần B. Cách setup máy

### B1. Máy S (Quang): Docker, middleware, HQ, bảng điều khiển

**B1.1. Tối 30/11, khi còn Internet:**

```powershell
git fetch --tags
```

```powershell
git checkout v1.0
```

```powershell
docker compose build middleware hq-demo
```

```powershell
docker compose pull sqlserver pos-gateway
```

```powershell
dotnet build clients/demo-console/DemoConsole/DemoConsole.csproj -c Debug
```

**B1.2. `.env`** (sửa tay, không commit):
- `DB_NAME=RTS_DB_DEMO`, `HQ_DB_NAME=RTS_HQ`
- `SYNC_INTERVAL=3600` (batch chỉ được tạo khi bấm "Chạy đồng bộ"), `SYNC_RETRY_BASE_SECONDS=10`
- `POS_BIND_ADDRESS` và `MIDDLEWARE_BIND_ADDRESS` = IP tĩnh của S, ví dụ `192.168.1.10`

**B1.3. Chứng chỉ:** chứng chỉ server phải có IP của S (`docs/demo/Sprint_3_Demo.md` mục 3). Không tạo lại CA.

**B1.4. Reset, khởi động, smoke check, reset lại:**

```powershell
docker compose up -d --wait sqlserver
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
```

```powershell
docker compose run --rm --no-deps --volume "${PWD}:/repo" --workdir /repo middleware python scripts/demo/sprint2_smoke.py
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/reset_demo_db.ps1 -NoBuild
```

Kết quả đúng sau lần reset cuối:
- Tồn: STORE-DN1 360, STORE-DN2 225, STORE-DN3 135.
- Hải Châu và Thanh Khê: Bread hết hạn sau 1 ngày, Fresh milk 2 ngày, Yogurt 3 ngày, Sponge cake đã hết hạn.
- HQ trống.
- Dòng `Forecast job ran.`

**B1.5. Xuất token cho A và B** (sau lần reset cuối cùng):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/export_terminal_tokens.ps1 -Terminal POS-DN1-01 -Staff staff_dn1 -Out .\out\A
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts/demo/export_terminal_tokens.ps1 -Terminal POS-DN2-01 -Staff staff_dn2 -Out .\out\B
```

Chép `out\A` sang máy A, `out\B` sang máy B bằng USB, rồi xóa thư mục `out` (trong đó có khóa riêng).

**B1.6. Bảng điều khiển:** tạo `clients/demo-console/DemoConsole/appsettings.Local.json` với `{ "FontSize": 16 }`, rồi mở:

```powershell
clients/demo-console/DemoConsole/bin/Debug/net8.0-windows/DemoConsole.exe
```

Tiêu đề có `(RTS_DB_DEMO)`, mọi tab xanh "Không có lỗi".

### B2. Mạng

- Router riêng không nối Internet. Cả 3 máy **cắm dây**, không dùng Wi-Fi. Windows đặt mạng **Private**.
- S có IP tĩnh. Mở firewall cổng 9443 và 8443 trên S (`scripts/demo/open_firewall.ps1`).
- Kiểm tra từ A và B: `Test-NetConnection <IP S> -Port 9443` và `-Port 8443` đều `True`.

### B3. Máy A (Khánh) và máy B (Sang)

1. Tối 30/11: `git checkout v1.0` rồi build Demo POS:

```powershell
dotnet build clients/demo-pos/DemoPos/DemoPos.csproj -c Debug
```

2. Chép nội dung `out\A` (hoặc `out\B`) vào thư mục gốc của repo.
3. `clients/demo-pos/DemoPos/appsettings.Local.json` trỏ về `https://<IP S>:9443/api/v1`, terminal `POS-DN1-01` (A) hoặc `POS-DN2-01` (B).
4. Chạy Demo POS:

```powershell
dotnet run --project clients/demo-pos/DemoPos/DemoPos.csproj --no-build
```

5. **Riêng máy A, Staff App:** publish ra `C:\RetailSync\StaffApp`, chép `ca.crt`. Tạo `appsettings.Local.json` với `BaseUrl https://<IP S>:8443/api/v1`, `TokenName staff_dn1`. Mở `StaffApp.exe`; tiêu đề phải hiện `RetailSync Staff App - STORE-DN1 | Nhân viên: staff_dn1`, giao diện tiếng Việt.

### B4. Quay hình và tiếng

- **Máy S:** OBS Studio quay toàn màn hình (bảng điều khiển là phần chiếu chính), 1920×1080, 30 fps. Micro cài áo hoặc micro điện thoại cho Kiệt, thu thành một track riêng.
- **Máy A và B:** OBS (hoặc Xbox Game Bar, `Win+Alt+R`) quay màn hình Demo POS và Staff App. Quang ghép hình nhỏ (picture-in-picture) khi dựng.
- **Một điện thoại** quay cảnh rút dây mạng ở màn 4, để người xem thấy đây là thao tác thật.
- Tắt thông báo Windows, Zalo, Teams trên cả 3 máy. Bật chế độ không làm phiền.
- Đầu mỗi đoạn, Quang vỗ tay một lần để dễ khớp hình và tiếng khi dựng.

---

## Phần C. Kịch bản quay và lời dẫn của Kiệt

Lời dẫn là gợi ý, Kiệt nói tự nhiên theo ý mình, không cần đọc từng chữ. Chữ *nghiêng* là thao tác trên màn hình.

### Màn 1: Mở đầu và kiến trúc (2 phút)

*Màn hình: slide sơ đồ kiến trúc, sau đó quay toàn cảnh 3 máy và router.*

> "Xin chào thầy cô và các bạn. Nhóm C1SE.24 xin giới thiệu RetailSync, một middleware khu vực giữa máy POS của nhiều cửa hàng và trụ sở HQ.
>
> Bài toán của chuỗi bán lẻ là: mỗi cửa hàng bán hàng liên tục, tồn kho phải đúng từng giây, không được đếm trùng khi mạng chập chờn, và cửa hàng vẫn phải bán được khi mất kết nối về trụ sở. Ngoài ra, hàng sắp hết hạn cần được phát hiện và giảm giá kịp thời, nhưng phải có kiểm soát.
>
> Hôm nay nhóm dùng 3 laptop. Máy S là trung tâm khu vực: middleware, cơ sở dữ liệu, cổng POS có xác thực chứng chỉ, và HQ mô phỏng. Máy A là cửa hàng Hải Châu, máy B là cửa hàng Thanh Khê, mỗi máy có một thu ngân thật bán hàng. Chiếc router này đóng vai mạng WAN riêng giữa cửa hàng và trung tâm, không nối Internet.
>
> Dữ liệu nằm ở ba nơi: máy POS chỉ giữ hàng đợi khi mất mạng, middleware giữ tồn kho và giao dịch của cả khu vực, còn HQ chỉ nhận tổng doanh số."

### Màn 2: Bán hàng thời gian thực (3 phút)

*Khánh bán 2 Fresh milk ở A → Sang bán một giỏ ở B → hai người bán cùng lúc. Quay bảng điều khiển trên S.*

> "Khánh ở Hải Châu bán 2 hộp sữa tươi. Trên màn hình trung tâm, tồn kho Hải Châu giảm ngay, và hệ thống trừ vào **lô có hạn sớm nhất trước**, gọi là FEFO, để hàng cũ được bán trước. Mỗi thay đổi đều có một dòng nhật ký audit.
>
> Sang ở Thanh Khê bán một giỏ nhiều món. Giao dịch của hai cửa hàng đổ về cùng một middleware, nhưng tồn kho mỗi cửa hàng được giữ riêng.
>
> Bây giờ hai bạn bấm thanh toán gần như cùng lúc. Cả hai đều thành công và tồn kho đều đúng, vì middleware khóa đúng lô hàng khi trừ, không để hai giao dịch giẫm lên nhau."

### Màn 3: Tin cậy và bảo mật (3 phút)

*Sang gửi lại giao dịch → kịch bản xung đột → chứng chỉ sai → Khánh trả hàng → hủy đơn.*

> "Mạng thật hay bị lỗi giữa chừng, nên POS có thể gửi lại cùng một giao dịch. Sang bấm gửi lại: hệ thống nhận ra trùng, trả về DUPLICATE, tồn kho không đổi. Mỗi giao dịch có một mã duy nhất.
>
> Nếu cùng mã đó mà nội dung khác, đây là xung đột, hệ thống từ chối với mã 409 và không thay đổi gì.
>
> Về bảo mật: mỗi máy POS có chứng chỉ riêng, kết nối qua TLS hai chiều. Gửi bằng chứng chỉ của máy khác thì bị chặn 403, và lần thử đó được ghi vào audit.
>
> Khánh trả lại một món: tồn kho được cộng lại đúng vào lô đã trừ lúc bán. Hủy một đơn chưa có trả hàng: mọi lô trở về như trước. Còn đơn đã có trả hàng thì không cho hủy, để số liệu không bị sai."

### Màn 4: Mất mạng WAN (3 phút)

*Quay bằng điện thoại cảnh Quang rút dây máy B. Sang bán 3 đơn; Khánh vẫn bán ở A. Cắm lại dây.*

> "Đây là phần nhóm muốn nhấn mạnh nhất. Quang rút dây mạng của cửa hàng Thanh Khê, giống như đường WAN bị đứt.
>
> Sang vẫn tiếp tục bán 3 đơn. Máy POS không báo lỗi với khách, mà lưu đơn vào hàng đợi trên ổ đĩa, kể cả khi tắt máy cũng không mất. Trong khi đó, Hải Châu không bị ảnh hưởng gì.
>
> Quang cắm lại dây. Máy B tự gửi bù 3 đơn **theo đúng thứ tự**, với đúng mã giao dịch cũ. Trên màn hình trung tâm: đủ 3 giao dịch, không mất, không trùng, tồn kho Thanh Khê đúng."

### Màn 5: Đồng bộ lên HQ (3 phút)

*Quang dùng tab Đồng bộ và HQ: chạy đồng bộ → HQ OFFLINE → bán thêm → HQ ONLINE → gửi snapshot.*

> "Mỗi giờ, middleware gom doanh số thành một batch cho mỗi cửa hàng và gửi lên HQ. Trong demo, nhóm bấm nút cho nhanh. Batch đi từ PENDING sang SENT, rồi ACKED khi HQ xác nhận. Tổng doanh số ở HQ khớp với giao dịch.
>
> Bây giờ HQ bị sập. Cửa hàng vẫn bán bình thường: middleware chạy độc lập. Batch mới nằm chờ ở PENDING, ghi số lần thử và lỗi, và thử lại với thời gian chờ tăng dần.
>
> HQ hoạt động lại. Các batch được gửi từ cũ đến mới, HQ không cộng trùng nhờ mã batch duy nhất.
>
> Còn nếu HQ gửi xuống một bản chụp tồn kho cũ thì sao? Hệ thống từ chối, vì tồn kho thật nằm ở cửa hàng; ghi đè bằng số cũ sẽ làm sai. Nhờ chỉ gửi tổng theo sản phẩm, dữ liệu lên HQ giảm gần 99% so với gửi từng giao dịch."

### Màn 6: Cận hạn, dự báo, đề xuất và giảm giá (5 phút)

*Quang chạy job cận hạn và job đề xuất → hạ mức giảm tối đa, chạy lại → Khánh mở Staff App: cảnh báo, tra mã vạch, đề xuất, Chấp nhận → Demo POS bán giá giảm → tab Giảm giá.*

> "Mỗi đêm, hệ thống tự chạy ba việc: kiểm tra hàng cận hạn, dự báo nhu cầu, và đưa ra đề xuất. Trong demo, Quang chạy ngay. Các lô sữa và bánh sắp hết hạn được cảnh báo, và hệ thống đề xuất giảm giá, thanh lý hoặc điều chuyển sang cửa hàng khác, kèm lý do.
>
> Nhưng đề xuất của máy không được đi thẳng tới nhân viên. Mọi đề xuất phải qua **guardrail**, tức các quy tắc kinh doanh do quản lý đặt: giảm tối đa bao nhiêu phần trăm, giá không dưới mức nào, hàng còn bao nhiêu ngày. Quang hạ mức giảm tối đa xuống rồi chạy lại: đề xuất vượt ngưỡng bị kéo về giới hạn, hoặc bị chặn và nhân viên không nhìn thấy.
>
> Khánh là nhân viên Hải Châu, mở Staff App. Cảnh báo được xếp theo độ khẩn: hàng đã hết hạn lên đầu. Tra một mã vạch đã hết hàng ở Hải Châu: app chỉ ra các cửa hàng **gần nhất trước**, **Sơn Trà (~1.7 km) đứng đầu rồi mới tới Thanh Khê (~4.4 km)**, kèm khoảng cách, để nhân viên hướng dẫn khách. Thứ tự này là do middleware xếp theo khoảng cách thật từ toạ độ seed, không phải thứ tự cửa hàng.
>
> Khánh mở một đề xuất giảm giá, xem lý do và kết quả guardrail, rồi bấm Chấp nhận. Quyết định được lưu kèm người và thời gian, không thể đổi lại.
>
> Điểm mới là: khi nhân viên chấp nhận giảm giá, **máy POS tự cập nhật giá** trong vòng một phút. Khánh bán món đó: giá niêm yết bị gạch ngang, khách trả giá đã giảm. Đúng như cửa hàng tiện lợi đổi giá hàng cận hạn vào đầu ngày.
>
> Trên tab Giảm giá, món vừa bán hiện 'Đã bán giá giảm: Có'. Chuyển sang 'Tất cả cửa hàng', nhân viên thấy cả giảm giá đang áp dụng ở Thanh Khê, để báo cho khách nơi nào đang bán rẻ hơn."

**Đoạn tab `Dự báo` — có điều kiện (chỉ quay nếu PB-53 merge trước freeze 12:00 30/11):**

Nếu PB-53 **đã** merge và tab `Dự báo` cùng hai biểu đồ có trong bản `v1.0`, quay thêm một đoạn 40–60 giây trong màn 6: mở tab, chỉ hai biểu đồ, và nói rõ bảng xếp theo thứ tự **thiếu hàng → thừa hàng → cân bằng**.

Nếu PB-53 **chưa** merge, **không** dựng lại cảnh này và **không** nói tab đó tồn tại. Thay vào đó quay lưới dự báo ở tab **Job** của Demo Console (cùng nội dung dự báo, khác chỗ hiển thị) và nói đúng một câu: bản `v1.0` chưa có tab `Dự báo` trên Staff App, số liệu dự báo đang xem ở bảng điều khiển. Ghi khoảng trống này vào §6 của `Report_Technical_Part.md`, không che đi.

Trong cả hai trường hợp, trước khi quay phải chạy job `forecast` (và `recommendation` cho đề xuất) rồi kiểm số dòng: 27 dòng dự báo trên seed 9 SKU, hoặc 90 dòng nếu danh mục đã thành 30 sản phẩm.

### Màn 7: Audit, doanh thu và số liệu đo (2 phút)

*Quang mở nhật ký audit (Auditor) → tab Doanh thu → slide bảng số liệu (dựng chèn phụ đề).*

> "Mọi thay đổi vừa rồi, từ bán hàng, từ chối, gửi trùng, đồng bộ, guardrail đến quyết định của nhân viên, đều được ghi lại và chỉ người kiểm toán mới xem được.
>
> Tab Doanh thu cho thấy doanh thu thuần theo ngày, theo danh mục và so sánh giữa các cửa hàng. Hệ thống tính theo thời điểm POS bán thật, nên đơn gửi bù sau khi mất mạng vẫn được tính đúng ngày.
>
> Cuối cùng là các số liệu nhóm đo bằng bộ mô phỏng:
> - độ trễ POS ở phân vị 95 là khoảng 227 mili giây khi có TLS hai chiều và độ trễ mạng 50 mili giây, dưới mục tiêu 500;
> - tra cứu liên cửa hàng khoảng 137 mili giây;
> - dữ liệu gửi HQ giảm gần 99%, 100% batch được xác nhận;
> - dự báo tốt hơn phương pháp cơ sở ở cả ba nhóm hàng;
> - phát hiện cận hạn đúng 32 trên 32 lô;
> - guardrail: 31.25% đề xuất đạt (5/16), 31.25% bị điều chỉnh (5/16), 37.50% bị chặn (6/16);
> - tỉ lệ nhân viên chấp nhận đề xuất 60.00% (6/10; riêng giảm giá 55.56% — 5/9).
>
> Cảm ơn thầy cô và các bạn đã theo dõi."

---

## Phần D. Kiểm tra sau mỗi đoạn và cách quay lại

| Màn | Đạt khi | Lỗi thường gặp và cách xử lý |
|---|---|---|
| 2 | Tồn giảm đúng, lô sớm nhất bị trừ, có audit | Bảng điều khiển chưa làm mới: chờ 5 giây hoặc bấm Làm mới |
| 3 | DUPLICATE, 409, 403 hiện đúng | 403 không hiện: kiểm tra đã chọn đúng kịch bản F12 "chứng chỉ terminal khác" |
| 4 | Đủ 3 đơn gửi bù, đúng thứ tự | Máy B không tự gửi: chờ tối đa 5 giây sau khi cắm dây; vẫn không thì quay lại màn 4 |
| 5 | ACKED, PENDING khi HQ OFFLINE, gửi bù khi ONLINE | Chưa có batch: phải bán ít nhất 1 đơn trước khi bấm Chạy đồng bộ |
| 6 | Có đề xuất, ADJUSTED/BLOCKED, POS bán giá giảm | Chưa có giá giảm trên POS: chờ đủ 60 giây; nếu quay lại màn 6 thì reset dữ liệu trước |
| 7 | Audit đủ, tab Doanh thu có số hôm nay | — |

Lỗi nặng (Docker hoặc SQL Server trên S hỏng): dừng quay, chạy lại B1.4 rồi B1.5 (token mới), chép lại token sang A và B, quay lại từ màn bị hỏng.

Hai lỗi PB-41 từng gặp **đã sửa trên `main`**: PB-41-2 (#95) cho script dự phòng đọc địa chỉ từ `.env` thay vì mặc định `localhost:8443`, và PB-41-3 (#97) cho Staff App không ghi vào control đã bị hủy khi đóng app giữa chừng. PB-41-4 (#98) và PB-41-7 (#94) cũng đã merge.

Hệ quả cho ngày quay:
- Script dự phòng chạy trên máy S **không cần** truyền `-BaseUrl` nữa; trên máy A/B vẫn truyền `-BaseUrl https://<IP S>:8443/api/v1` vì `.env` của A/B không có địa chỉ của S.
- Trong Staff App, nếu lỡ đóng app giữa lúc đang gọi API thì mở lại bình thường, không còn lỗi ghi vào control đã hủy. Vẫn nên chờ có kết quả rồi mới bấm tiếp để đoạn quay liền mạch.

---

## Phụ lục: dự phòng khi quay và dựng

### 1. Dự phòng ngoài các lỗi trong Phần D

| Sự cố | Xử lý |
|---|---|
| A hoặc B không gọi được S | Kiểm IP, firewall cổng 9443/8443, mạng Windows ở chế độ Private; chuyển sang laptop dự phòng đã cài sẵn như A hoặc B |
| Lỗi chứng chỉ | Tạo lại chứng chỉ trên S sao cho SAN có IP của S, chép `ca.crt` sang A/B, quay lại đoạn bị ảnh hưởng; không tạo lại CA |
| Bảng điều khiển không mở | Quay bằng các script một thao tác (`sync_run.ps1`, `hq_mode.ps1`, `run_job.ps1`, `cross_store.ps1`, `audit_tail.ps1`) và quay terminal |
| Router hoặc mạng riêng hỏng | Dùng hotspot dự phòng; nếu không còn cách nào, chạy hai Demo POS trên máy S và mô phỏng mất WAN bằng cách dừng pos-gateway |
| Micro hỏng | Thu bằng điện thoại, đồng bộ sóng khi dựng; không lồng tiếng sau |
| Hết giờ | Bỏ bước guardrail của màn 6 và bước bán đồng thời của màn 2, đúng thứ tự Kiệt đã duyệt |
| Thiếu hình kiến trúc | Repo không có file hình; xuất hình từ tài liệu thiết kế ra PNG trước ngày quay và để ngoài repo |
| Ổ quay đầy | Chuyển sang ổ ngoài; kiểm dung lượng trước mỗi màn |

### 2. Quy tắc dữ liệu giữa các đoạn

- Sau mỗi lần reset, chạy thêm job recommendation: B1.4 chỉ chạy forecast, nên tập đề xuất `PENDING` cho màn 6 phải được tạo trước khi quay.
- Kiểm số dòng sau reset: 27 dòng dự báo (9 SKU × 3 cửa hàng). Nếu PB-52 merge và danh mục thành 30 sản phẩm, con số là 90 và mọi số trong `docs/reports/` phải được đo lại trước khi quay màn 6, 7.
- Không quay trên `RTS_DB` và không quay trên trạng thái cuối của buổi hồi quy 30/11.
- Không sửa số trong báo cáo cho khớp video; video phải đọc đúng số trong `docs/reports/`.
- Giữ take cũ của đoạn vừa quay lại cho đến khi dựng xong, để đối chiếu nếu Kiệt đổi lời dẫn.

### 3. Dựng và xuất bản cuối

1. Ghép theo màn; tiêu đề màn dạng lower-third tiếng Việt, không thay lời dẫn bằng text card.
2. Giữ lời dẫn trực tiếp; chỉ cắt khoảng lặng và thao tác lặp, không cắt bằng chứng.
3. Che token, mật khẩu, fingerprint chứng chỉ và thông báo có tên máy cá nhân nếu xuất hiện.
4. Bản dựng 15–18 phút; nếu dài hơn 20 phút thì cắt phần lặp, không cắt bằng chứng.
5. Xuất 1080p H.264 và thêm bản 720p để tải lên; kiểm âm lượng; thêm phụ đề `.srt` nếu kịp.
6. Lưu master ngoài repo; chỉ đưa link vào báo cáo, không đưa đường dẫn cá nhân vào tài liệu.
