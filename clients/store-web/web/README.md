# Store Web — hướng dẫn dùng giao diện

Web bán hàng/tra cứu của RetailSync. Khách hàng tìm món hàng mình cần, hệ thống chỉ ngay
**cửa hàng gần nhất còn sẵn hàng**, dựa trên vị trí khách chọn hoặc định vị GPS.

```text
Khách hàng  →  Tìm món hàng  →  Gợi ý cửa hàng gần nhất còn hàng  →  Xem kho của cửa hàng đó
```

Có 2 phần trong cùng một web:

| Phần | Dành cho | Đường dẫn |
|---|---|---|
| **Shop** | Khách hàng: tìm hàng, chọn vị trí, tài khoản | `/`, `/login`, `/register`, `/account` |
| **Chi nhánh** | Xem danh mục & tồn kho chi tiết từng cửa hàng | `/stores`, `/stores/:storeId`, `/stores/:storeId/products/:sku` |

- `web/` — ứng dụng React + TypeScript + Vite (thư mục này).
- `../api/` — API FastAPI. Đọc dữ liệu cửa hàng (chỉ đọc) và ghi tài khoản khách vào CSDL riêng.
- Bản build được API phục vụ tại `http://127.0.0.1:5180` → **một tiến trình, một cổng**.

Chi tiết API, cơ sở dữ liệu và kiểm thử backend: xem `../README.md`.

## 1. Mở web

Nếu máy đã có người chạy sẵn API ở cổng 5180, chỉ cần mở:

```text
http://127.0.0.1:5180
```

Nếu chưa, làm theo mục 2.

## 2. Chạy lần đầu

Cần: Node ≥ 20.19 hoặc ≥ 22.12, pnpm, Docker Desktop (SQL Server), Python (API).

```powershell
# 1) CSDL cửa hàng (từ thư mục gốc repo, chỉ một lần)
cd G:\RetailSync
docker compose up -d --wait sqlserver
docker compose run --rm migrate

# 2) Build giao diện
cd clients/store-web/web
pnpm install
pnpm build

# 3) Cài đặt API
cd ..\api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# 4) Tạo CSDL tài khoản khách hàng RTS_CUSTOMER (chỉ một lần)
.\.venv\Scripts\python.exe tools\init_customer_db.py

# 5) Chạy API (API phục vụ luôn bản build ở bước 2)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180
```

Mở `http://127.0.0.1:5180`.

> Máy chưa có Python 3.12 thì dùng `py -3.11`. Windows cần **ODBC Driver 18 for SQL Server**
> (64-bit) để API kết nối được.

Lần sau chỉ cần bước 5. Sau khi sửa giao diện phải chạy lại `pnpm build` rồi khởi động lại API.

## 3. Chế độ phát triển (sửa code có hot reload)

```powershell
# Terminal 1 — API
cd clients/store-web/api
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 5180 --reload

# Terminal 2 — giao diện
cd clients/store-web/web
pnpm dev
```

Mở `http://localhost:5173`. Vite tự chuyển `/api` sang cổng 5180 nên không cần cấu hình CORS.

## 4. Các màn hình

### 4.1. Khám phá — `/`

Trang chủ của khách hàng:

- **Ô tìm kiếm lớn**: nhập tên hoặc SKU (Vd: "sữa", "milk", "SKU-0001"). Kết quả cập nhật ngay.
- **Dãy danh mục**: Bakery / Dairy / Dry goods… bấm để lọc.
- **Lưới sản phẩm**: mỗi thẻ hiện danh mục, tên, giá và **hộp gợi ý** ở dưới:
  - Có hàng: tên cửa hàng gần nhất, **địa chỉ đường**, quãng đường đi (km), số lượng còn bán,
    link **Xem kho hàng →**.
  - Không cửa hàng nào còn hàng: "Tạm hết hàng ở tất cả các cửa hàng lân cận".

Khoảng cách là **quãng đường đi thực tế** do API tính qua OSRM. Nếu máy chủ routing không trả lời
được, API quay về đường chim bay và web ghi rõ `(đường chim bay)` — hai loại số này không so sánh
được với nhau nên không bị trộn lẫn. Không có nhãn nghĩa là số km đường đi.

Không nhập gì thì trang hiển thị toàn bộ danh mục (sản phẩm nổi bật).

### 4.2. Đổi vị trí — bấm thanh địa chỉ trên header

Hệ thống tính khoảng cách tới từng cửa hàng từ vị trí này. Có 3 cách:

1. **📍 Dùng vị trí hiện tại (GPS)** — trình duyệt hỏi quyền, lấy toạ độ thật của thiết bị.
2. **Địa chỉ của tôi** (chỉ khi đã đăng nhập) — danh sách đã lưu; bấm để chọn.
3. **Địa điểm gợi ý tại Đà Nẵng** — 4 địa chỉ mẫu dùng được khi không muốn bật định vị.

Địa chỉ đã chọn được nhớ trong `localStorage`, nên lần sau mở vẫn đúng.
Vị trí mặc định là **Trung tâm Hải Châu, Đà Nẵng**.

> Nếu từ chối quyền vị trí, web hiện "Bạn đã từ chối chia sẻ vị trí. Hãy chọn địa chỉ có sẵn."
> chứ không hỏng trang.

### 4.3. Đăng ký — `/register`

Họ tên, email, mật khẩu (**ít nhất 8 ký tự**, kiểm ngay trên web). Đăng ký xong được đăng nhập luôn.

Email trùng báo "Email này đã được đăng ký."

### 4.4. Đăng nhập — `/login`

Email + mật khẩu. Sai tài khoản hay sai mật khẩu đều báo chung **"Email hoặc mật khẩu không đúng."**
để không tiết lộ email nào đã tồn tại.

Phiên đăng nhập nằm trong **cookie httpOnly**, JavaScript không đọc được, nên token không thể bị
đánh cắp qua XSS. Phiên mặc định sống 7 ngày.

### 4.5. Tài khoản — `/account`

- **Thông tin cá nhân**: họ tên, email, mã khách hàng.
- **Sổ địa chỉ đã lưu** (tối đa 20): thêm, chọn làm vị trí hiện tại, xoá.
  Địa chỉ mới lưu lấy toạ độ của vị trí đang chọn — vì demo không gọi dịch vụ geocode bên ngoài.
- **Đăng xuất** ở đây hoặc trên header.

### 4.6. Chi nhánh — `/stores`

Danh sách 3 cửa hàng, mỗi thẻ có địa chỉ đường, số SKU và tổng đơn vị bán được. Bấm để xem danh mục.

### 4.7. Sản phẩm của cửa hàng — `/stores/:storeId`

- Tìm theo tên/SKU, lọc danh mục, "chỉ còn hàng", sắp xếp Tên/Giá/Còn bán, phân trang 25 dòng.
- Bảng: Tên, SKU, Danh mục, Giá, **Còn bán**, Hạn gần nhất, **Gần nhất còn hàng**.
- Link sản phẩm dẫn tới trang chi tiết của **chính cửa hàng đó**.
- Bảng liệt kê **toàn bộ danh mục của hệ thống**, không chỉ hàng chi nhánh này nhập — nhờ vậy khách
  thấy được món mình cần rồi được chỉ sang chi nhánh có hàng. Dòng "21 sản phẩm trong hệ thống ·
  13 sản phẩm cửa hàng này đang bán" tách bạch hai con số đó.
- Cột **Gần nhất còn hàng**: `tại đây` khi chi nhánh đang xem còn hàng (kể cả khi chi nhánh khác
  gần hơn về địa lý), ngược lại là tên cửa hàng gần nhất còn hàng kèm số km, bấm được để sang đó.
  Không cửa hàng nào còn hàng → `—`.

> **"Còn bán" không phải tổng tồn kho.** Cột này chỉ đếm lô còn hạn. Hàng hết hạn vẫn nằm trong
> tồn kho nhưng không bán được, nên sản phẩm có tồn vẫn có thể gắn nhãn **hết hàng**.

### 4.8. Chi tiết sản phẩm — `/stores/:storeId/products/:sku`

Thẻ thông tin (SKU, mã vạch, danh mục, giá, Còn bán, Tổng tồn kèm số đơn vị hết hạn, Sắp hết hạn)
và bảng lô: mã lô, hạn dùng, số lượng, trạng thái. Lô hết hạn bị gạch ngang.

- Lô hết hạn **đúng hôm nay vẫn bán được**.
- Mặc định ẩn lô đã hết số lượng; tick **"Hiện cả lô đã hết số lượng"** để xem.

### 4.9. Đường dẫn không tồn tại — `*`

Trang "Không tìm thấy trang" kèm link về danh sách cửa hàng.

## 5. Bộ lọc nằm trong URL

Bộ lọc của trang `/stores/:storeId` được ghi vào đường dẫn, nên **chia sẻ link** hoặc
**back/forward** đều đúng:

```text
/stores/STORE-DN1?q=milk&category=Dairy&in_stock=true&sort=price&limit=25&offset=25
```

| Tham số | Giá trị | Mặc định |
|---|---|---|
| `q` | Tên hoặc SKU, tối đa 100 ký tự | rỗng |
| `category` | Một danh mục | tất cả |
| `in_stock` | `true` = chỉ còn hàng | không lọc |
| `sort` | `name` \| `price` \| `sellable` | `name` |
| `limit` | 1–200 | 25 |
| `offset` | ≥ 0 | 0 |

Giá trị lạ (`sort=abc`, `limit=9999`) được bỏ qua và quay về mặc định, không làm hỏng trang.

## 6. Trạng thái và thông báo

| Trạng thái | Người dùng thấy |
|---|---|
| Đang tải | Khung xương (skeleton) + thông báo đang tải |
| Rỗng | "Không có sản phẩm khớp bộ lọc.", "Chưa có cửa hàng nào đang hoạt động." |
| Hết hàng mọi nơi | "Tạm hết hàng ở tất cả các cửa hàng lân cận" |
| Lỗi kết nối CSDL (503) | "Không kết nối được cơ sở dữ liệu" + nút **Thử lại** |
| Cửa hàng không tồn tại | "Không tìm thấy cửa hàng" + link về danh sách |
| Sản phẩm không có | "Không tìm thấy sản phẩm" + link về cửa hàng |
| Bộ lọc sai (422) | "Bộ lọc không hợp lệ" (không lộ JSON thô) |
| Chưa đăng nhập vào `/account` | "Bạn chưa đăng nhập" + nút đăng nhập |

Giá hiển thị dạng `32.000 ₫`, ngày dạng `13/11/2026`, số `null` hiển thị `—`.

## 7. Kiểm thử và kiểm tra mã nguồn

Không cần cơ sở dữ liệu và không cần API thật (dùng msw):

```powershell
cd clients/store-web/web
pnpm test        # 30 test
pnpm typecheck   # tsc --noEmit
pnpm lint        # oxlint
```

Test phủ: trang chủ + gợi ý cửa hàng gần nhất, tìm kiếm/lọc, đăng nhập/đăng ký, sổ địa chỉ,
danh sách cửa hàng, bảng sản phẩm, lô hết hạn, và 4 trạng thái rỗng/lỗi/404/422.

## 8. Sự cố

| Hiện tượng | Việc cần làm |
|---|---|
| `http://127.0.0.1:5180` trả **404** | Chưa build: chạy `pnpm build` trong `web/` rồi khởi động lại API |
| Trang trắng, console báo lỗi tải `/assets/...` | Build cũ: chạy lại `pnpm build` |
| Đăng nhập/đăng ký báo lỗi máy chủ | Chưa tạo CSDL khách: chạy `python tools\init_customer_db.py` |
| "Không kết nối được cơ sở dữ liệu" | SQL Server chưa chạy hoặc sai `DB_HOST`/`SQLSERVER_PORT`; kiểm `docker compose ps` |
| GPS không hoạt động | Trình duyệt chỉ cho định vị trên `localhost` hoặc HTTPS; dùng địa chỉ mẫu |
| `pnpm dev` mở được nhưng gọi API lỗi | API chưa chạy ở 5180 |
| `pnpm install` lỗi | `pnpm install --force`; kiểm Node ≥ 20.19/22.12 |
| Cổng 5173/5180 bận | Đổi cổng khi chạy và sửa `server.proxy` trong `vite.config.ts` |
| Dữ liệu cửa hàng sai | Chạy lại `docker compose run --rm migrate` từ thư mục gốc repo |

## 9. Ghi chú kỹ thuật

- **CSDL tách biệt**: dữ liệu cửa hàng (đọc) và dữ liệu khách hàng (ghi) nằm ở 2 database khác
  nhau (`RTS_DB_DEMO` và `RTS_CUSTOMER`), nên lỗi phía khách không thể làm hỏng tồn kho.
- **Mật khẩu**: PBKDF2-HMAC-SHA256, 210.000 vòng, salt ngẫu nhiên 16 byte.
- **Session**: token ngẫu nhiên 32 byte; CSDL chỉ lưu SHA-256 của token.
- **Khoảng cách**: OSRM `table` (quãng đường đi, làm tròn 100 m) tính ở phía API nên mọi client cho
  cùng kết quả; fallback đường chim bay khi routing không dùng được, có gắn cờ để web hiện nhãn.
- **Chỉ gợi ý cửa hàng còn hàng**: cửa hàng hết sạch lô còn hạn bị loại khỏi gợi ý.
- Không gọi dịch vụ bản đồ/geocode bên ngoài; mọi thứ chạy offline trong mạng nội bộ.
