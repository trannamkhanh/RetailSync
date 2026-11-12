# Kế hoạch: Shop UI kiểu WinMart — chi tiết sản phẩm, giỏ hàng, bộ lọc, gợi ý tìm kiếm

> Trạng thái: **bản kế hoạch**, chưa code, chưa đổi schema.
> Phạm vi: `clients/store-web/` (app độc lập). Không sửa `middleware/`, `compose.yaml`,
> `docs/design/openapi.yaml`, không sửa migration 001–005.
> Người làm: Quang. Nhánh: `Quang` → `main`.
> Tài liệu này thay thế phần UI trong `PLAN.md` mục 6; `PLAN.md` vẫn giữ nguyên phạm vi gốc.

---

## 0. Chốt với người đặt hàng (11/11/2026)

| # | Câu hỏi | Quyết định |
|---|---|---|
| 1 | Giữ hàng / thanh toán trước | **Không làm bây giờ.** Đây là kế hoạch tương lai — đặc tả giữ nguyên ở Phụ lục B |
| 2 | Bảng mới cho chi tiết sản phẩm, giỏ, đơn, hold | **Không thêm bảng, không đổi schema trong đợt này** |
| 3 | Trang chi tiết sản phẩm | **Vẫn phải làm**, chỉ dùng dữ liệu đang có |
| 4 | Giỏ hàng | **Làm ngay**, nhưng là giỏ phía trình duyệt; máy chủ chỉ *đọc* để tính cửa hàng còn đủ hàng |
| 5 | Trả khi đến lấy | Không có trong đợt này (chỉ thuộc luồng đặt hàng tương lai) |
| 6 | Đánh giá / rating | Không |
| 7 | Thêm SKU mới để giống WinMart | Không; chỉ làm giàu cách trình bày 21 SKU hiện có |
| 8 | Trang `/stores/:id` (bảng tồn kho) | Giữ nguyên cho nhân viên |
| 9 | Tên thương hiệu | Giữ RetailSync (không mạo danh WinMart), chỉ bám bố cục |

**Hệ quả quan trọng:** toàn bộ 4 tính năng của đợt này làm được **trên 6 bảng đang có**
(`store`, `product`, `inventory`, `product_batch` + 3 bảng khách hàng đã tạo trong `RTS_CUSTOMER`),
không cần migration, không cần cột mới. Những gì cần thêm cột/bảng được đẩy sang Phụ lục B.

---

## 1. Mục tiêu & nghiệm thu

**Mục tiêu.** Giao diện shop gần với winmart.vn: header có ô tìm kiếm gợi ý, banner, card sản phẩm,
trang danh mục có sidebar lọc nhiều điều kiện, trang chi tiết sản phẩm đầy đủ, giỏ hàng cho biết
**cửa hàng gần nhất còn đủ tất cả mặt hàng trong giỏ**.

**Nghiệm thu (đo được):**

1. Tìm "sua" (không dấu) vẫn ra "Sữa chua uống Yakult"; gõ ≥2 ký tự thấy dropdown gợi ý; ↑↓/Enter/Esc chạy được.
2. Lọc đồng thời: 2 danh mục + khoảng giá + "chỉ còn hàng" + sắp xếp giá giảm; mọi điều kiện nằm trong URL, back/forward đúng; số đếm cạnh mỗi danh mục khớp kết quả khi bỏ chọn danh mục đó.
3. `/san-pham/SKU-0001` mở trực tiếp (dán link, F5) vẫn render; có ảnh, giá, tồn tổng, danh sách cửa hàng còn hàng kèm khoảng cách, sản phẩm tương tự, nút thêm vào giỏ.
4. Giỏ có 3 món của 3 cửa hàng khác nhau → hiện đúng cửa hàng **đủ cả 3** (hoặc nói rõ "không cửa hàng nào đủ" + kế hoạch đi 2 nơi + món nào thiếu ở đâu).
5. `pytest` (API) xanh, `pnpm test` / `pnpm typecheck` / `pnpm lint` xanh; `test_read_only.py` vẫn xanh — bằng chứng DB cửa hàng không bị ghi.
6. Trang nhân viên `/stores/:id` giữ nguyên bảng tồn kho, không đổi hành vi.

---

## 2. Trả lời trực tiếp: DB có gì, cần thêm gì

### 2.1. Hiện có (đủ cho đợt này)

| Bảng | Cột dùng được | Phục vụ |
|---|---|---|
| `dbo.product` | `sku`, `barcode`, `name`, `category`, `unit_price`, `image_url` | card, chi tiết, lọc giá, tìm kiếm |
| `dbo.inventory` | `store_id`, `sku`, `quantity` | tồn thô (không dùng để hiển thị "còn bán") |
| `dbo.product_batch` | `store_id`, `sku`, `expiry_date`, `quantity` | `sellable_quantity`, hạn gần nhất, lọc "còn hàng" |
| `dbo.store` | `store_id`, `name`, `region_id`, `address_text`, `latitude`, `longitude`, `is_active` | gợi ý cửa hàng, khoảng cách |
| `RTS_CUSTOMER` | `customer`, `customer_session`, `customer_address` | đăng nhập, sổ địa chỉ (không đổi) |

`dbo.category`, `dbo.promotion`, `dbo.product_image`, `dbo.product_spec` **chưa có** → đợt này
dùng `product.category` (varchar) làm danh mục phẳng và `product.image_url` làm ảnh duy nhất.

### 2.2. Cần thêm cho đợt này: **không gì**

Không migration, không seed, không `ALTER TABLE`. Mọi thứ còn thiếu về nội dung (mô tả, thương
hiệu, gallery, giá khuyến mãi, rating) được ghi thành Phụ lục B để làm sau, kèm DDL nháp sẵn.

### 2.3. Vấn đề kỹ thuật phải xử lý dù không đổi schema

**Collation.** SQL Server mặc định `SQL_Latin1_General_CP1_CI_AS` là **accent-sensitive**:
`name LIKE '%sua%'` **không** khớp `Sữa`. Vì không thêm cột persisted, mọi câu tìm kiếm dùng
`p.name COLLATE Latin1_General_CI_AI LIKE :q_like`. Hệ quả: mất index seek — chấp nhận được ở
21 SKU; ghi ngưỡng xem lại (≈50.000 SKU) vào README. Đây là điểm dễ sai nhất của đợt này và có
test riêng.

---

## 3. Kiến trúc & ranh giới

Giữ nguyên: `web/` (React 19 + TS + Vite) gọi `/api/*`; `api/` (FastAPI) đọc store DB chỉ SELECT,
ghi `RTS_CUSTOMER` chỉ cho auth/địa chỉ. Không thêm service, không thêm biến môi trường bắt buộc.

Hai điểm khác biệt so với hiện tại:

1. **Giỏ hàng nằm ở trình duyệt** (localStorage + React context), không có bảng `cart`.
   Máy chủ chỉ nhận danh sách SKU/số lượng rồi **đọc** tồn để trả lời "cửa hàng nào đủ hàng".
   Đánh đổi: giỏ không đồng bộ giữa thiết bị và mất khi xoá dữ liệu trình duyệt — chấp nhận cho
   demo, không cản trở việc chuyển sang giỏ phía máy chủ ở Phụ lục B (chỉ thay lớp lưu trữ).
2. **Danh mục shop là route riêng** (`/tim-kiem`, `/danh-muc/:slug`) tách khỏi trang nhân viên
   (`/stores/*`). Không còn cảnh một bảng HTML phục vụ hai đối tượng.

`Change Necessity`: cần code vì (a) trang chi tiết hiện tại gắn chặt `storeId`, không mở trực tiếp
theo SKU được; (b) bộ lọc hiện chỉ có 1 danh mục + 1 kiểu sắp xếp; (c) không có endpoint gợi ý và
không có endpoint trả lời "cửa hàng nào đủ cả giỏ". Không thể giải bằng cấu hình/tài liệu.

`TDD Route`: mode `off` (mặc định của phiên), decision `skipped`, authority `default`; kiểm chứng
bằng bộ test sẵn có + test mới viết kèm từng task (xem mục 8). Không có ép buộc RED-first.

`Ripple Signal Triage`: có chạm hợp đồng API (thêm/sửa endpoint trong app) và chạm chủ sở hữu
"danh sách sản phẩm" ở web (bảng cũ → card mới). Chủ sở hữu chuẩn:
- Dữ liệu + luật: `api/app/queries/products.py` (một chỗ duy nhất cho mệnh đề lọc/giá/tồn).
- Hợp đồng: `web/src/api/types.ts` cập nhật cùng lúc, không để hai shape.
- Không giữ song song hai màn hình catalog: `FilterBar` + `ProductTable` chuyển thành
  `FilterPanel` + `ProductCard`, chỉ còn dùng ở có một nơi; trang nhân viên dùng lại bảng qua
  `variant` chứ không nhân bản.

---

## 4. Hợp đồng API (thêm/xoá, tất cả chỉ đọc)

Quy ước giữ nguyên: JSON `snake_case`, tiền là **string 2 chữ số thập phân**, lỗi
`{outcome, code, message}`, mọi câu SQL nằm trong `app/queries/` và bắt đầu bằng `SELECT`.

### 4.1. `GET /api/products/{sku}` — chi tiết toàn cục (mới)

Query: `latitude`, `longitude` (tuỳ chọn — có thì mới trả khoảng cách).

```json
{
  "item": {
    "sku": "SKU-0001", "barcode": "8930000000011", "name": "Fresh milk 1L",
    "category": "Dairy", "unit_price": "32000.00", "image_url": "/products/fresh-milk.jpg",
    "sellable_quantity": 56,
    "nearest_expiry": "2026-11-14",
    "stores": [
      { "store_id": "STORE-DN1", "name": "Cửa hàng Hải Châu",
        "address_text": "123 Bạch Đằng, Hải Châu, Đà Nẵng",
        "sellable_quantity": 40, "nearest_expiry": "2026-11-14",
        "distance_km": 0.4, "distance_kind": "road" }
    ]
  },
  "related": [
    { "sku": "SKU-0002", "name": "Sữa chua uống Yakult", "category": "Dairy",
      "unit_price": "28000.00", "image_url": "/products/drinking-yogurt.jpg",
      "sellable_quantity": 18, "nearest": { "store_id": "STORE-DN1", "distance_km": 0.4,
      "distance_kind": "road", "sellable_quantity": 18 } }
  ]
}
```

- `stores` chỉ gồm cửa hàng `is_active = 1` và `sellable_quantity > 0`, sắp theo khoảng cách.
- `related`: cùng `category`, khác SKU, tối đa 8, ưu tiên còn hàng rồi tên.
- 404 `NOT_FOUND` khi SKU không có trong catalog.
- Không có toạ độ → `distance_km = null`, `distance_kind = null`; web ẩn khoảng cách chứ không bịa số.

### 4.2. `GET /api/shop/search` — mở rộng (endpoint catalog duy nhất)

Giữ route, **giữ tương thích** (`q`, `latitude`, `longitude`, `category`, `limit` vẫn như cũ),
thêm:

| Tham số | Kiểu | Ghi chú |
|---|---|---|
| `q` | string, ≤100 | nay **tuỳ chọn**; rỗng = duyệt theo bộ lọc |
| `category` | repeated | `?category=Dairy&category=Bakery`; vắng = tất cả |
| `price_min`, `price_max` | int (đồng) | so với `unit_price`, `price_min <= price_max` |
| `in_stock` | bool | chỉ sản phẩm còn bán được ở **ít nhất một** cửa hàng |
| `near_km` | float ≤ 50 | cần `latitude`+`longitude`; chỉ sản phẩm còn hàng trong bán kính |
| `sort` | `relevance\|name\|price_asc\|price_desc\|sellable` | mặc định `relevance` khi có `q`, `name` khi không |
| `offset` | int | phân trang (mới; trước chỉ `limit`) |

Response thêm `facets` (đếm **cùng** bộ lọc, trừ chính chiều đang đếm) và `total`:

```json
{
  "q": "sua", "latitude": 16.06, "longitude": 108.22, "total": 3,
  "facets": {
    "categories": [{ "name": "Dairy", "count": 3 }, { "name": "Bakery", "count": 1 }],
    "price_buckets": [
      { "label": "Dưới 20.000 ₫", "min": 0, "max": 20000, "count": 1 },
      { "label": "20.000 – 50.000 ₫", "min": 20000, "max": 50000, "count": 2 }
    ]
  },
  "items": [ /* ShopProduct như hiện tại */ ]
}
```

`relevance` = khớp ở đầu tên trước, rồi tới khớp giữa tên, rồi SKU/barcode (một `CASE` trong
`ORDER BY`, không dùng engine full-text).

### 4.3. `GET /api/search/suggest?q=&limit=8` — gợi ý (mới)

```json
{
  "q": "sua",
  "products": [ { "sku": "...", "name": "...", "category": "...", "unit_price": "28000.00",
                  "image_url": "...", "sellable_quantity": 18,
                  "nearest": { "store_id": "STORE-DN1", "name": "Cửa hàng Hải Châu",
                               "distance_km": 0.4, "distance_kind": "road",
                               "sellable_quantity": 18 } } ],
  "categories": [ { "name": "Dairy", "count": 4 } ]
}
```

- `q` 1 ký tự → 422 `VALIDATION_ERROR` (đồng bộ với hành vi UI: chỉ gọi từ 2 ký tự).
- Tối đa 8 sản phẩm + 5 danh mục; sắp theo relevance như 4.2.
- Không có `nearest` thì bỏ trường này (không trả `null` giả).
- **Không** trả "tìm kiếm phổ biến": chưa có log. Lịch sử gần đây do client tự lưu localStorage.
- Highlight: client tự tô (so khớp không dấu ở JS). Server không gửi range — tránh lệch offset
  giữa NFD/NFC.

### 4.4. `POST /api/cart/availability` — cửa hàng đủ cả giỏ (mới, **chỉ đọc**)

Body (giới hạn 50 dòng, mỗi `quantity` 1..99):

```json
{ "latitude": 16.06, "longitude": 108.22,
  "items": [{ "sku": "SKU-0001", "quantity": 2 }, { "sku": "SKU-0013", "quantity": 1 }] }
```

```json
{
  "item_count": 2,
  "stores": [
    { "store_id": "STORE-DN2", "name": "Cửa hàng Thanh Khê",
      "address_text": "...", "distance_km": 2.1, "distance_kind": "road",
      "complete": true, "covered_count": 2,
      "lines": [{ "sku": "SKU-0001", "requested": 2, "available": 20 }] },
    { "store_id": "STORE-DN1", "name": "Cửa hàng Hải Châu",
      "address_text": "...", "distance_km": 0.4, "distance_kind": "road",
      "complete": false, "covered_count": 1,
      "missing": [{ "sku": "SKU-0013", "requested": 1, "available": 0 }],
      "lines": [{ "sku": "SKU-0001", "requested": 2, "available": 40 }] }
  ],
  "best": "STORE-DN2",
  "split_plan": null
}
```

Luật:
- `available` = tổng batch `quantity > 0` và `expiry_date >= today_local` tại cửa hàng đó.
- `complete = true` khi **mọi** dòng thoả `available >= requested`.
- `stores` sắp: `complete` trước, trong mỗi nhóm theo `distance_km`; chỉ trả cửa hàng đang hoạt động.
- `best` = `store_id` của cửa hàng `complete` gần nhất, `null` nếu không có.
- Không cửa hàng nào đủ → `split_plan`:
  `{ "store_count": 2, "stores": [ { "store_id", "name", "distance_km", "distance_kind",
  "lines": [{ "sku", "quantity" }] } ] }` — ghép tham lam: mỗi SKU lấy cửa hàng gần nhất còn đủ
  số lượng đó; gộp theo cửa hàng; nếu vẫn thiếu ở mọi nơi → thêm
  `"unavailable": [{ "sku", "requested", "best_available" }]`.
- SKU không tồn tại trong catalog → `unknown: ["SKU-X"]`, không 500.
- Đây là POST vì body dài, nhưng **không ghi gì**: không `INSERT/UPDATE/DELETE`, không commit.
  Ghi chú này phải nằm trong docstring router (test_read_only dựa vào danh sách router).

### 4.5. `GET /api/stores/{store_id}/products` — mở rộng nhẹ

Thêm `price_min`, `price_max`, `sort=price_asc|price_desc` (giữ `name|price|sellable` cũ), dùng
chung mảnh SQL lọc với 4.2. Không thêm `facets` (trang nhân viên không cần).

### 4.6. Không đổi
`/api/health`, `/api/stores`, `/api/stores/{id}`, `/api/categories`, `/api/stores/{id}/products/{sku}`,
`/api/shop/addresses*`, `/api/auth/*`. `/api/categories` vẫn là nguồn danh mục phẳng duy nhất.

---

## 5. Thuật toán & SQL (một chỗ duy nhất trong `queries/`)

`queries/products.py` giữ các mảnh dùng chung, không nhân bản giữa catalog và trang cửa hàng:

```
_BATCH_TOTALS        # hiện có: sellable/expired/nearest_expiry theo (store, sku)
_WHERE_TEXT          # mới: q (CI_AI), category IN (...), price range
_ORDER_BY            # mở rộng: name | price_asc | price_desc | sellable | relevance
```

- `q` chống wildcard bằng `escape_like` hiện có; `COLLATE Latin1_General_CI_AI` đặt trên `p.name`.
- `category IN :cats` dùng `bindparam(expanding=True)`; danh sách rỗng ⇒ bỏ mệnh đề (không `IN ()`).
- Giá: `p.unit_price >= :price_min` / `<= :price_max`; đơn vị đồng, không nhân 100.
- `near_km`: 1 câu `SELECT store_id, sku, SUM(...)` cho **tất cả** SKU của trang (không N+1), lọc
  cửa hàng theo khoảng cách tính từ `routing.store_distances` (một request OSRM, fallback haversine).
- Facets: 2 câu `COUNT(*) ... GROUP BY category` và `CASE` chia bucket giá, mỗi câu dùng bộ lọc
  **trừ** chiều của chính nó.
- `POST /api/cart/availability`: 1 câu tồn theo `sku IN (...)` (mở rộng `STORE_STOCK_FOR_SKUS` hiện
  có, thêm `nearest_expiry`), 1 câu danh sách cửa hàng active (đã có), 1 request OSRM. Không có
  truy vấn theo từng dòng.
- Chi tiết 4.1: 1 câu sản phẩm + 1 câu tồn mọi cửa hàng cho SKU đó + 1 câu `related` + 1 request OSRM.

---

## 6. Giao diện

### 6.1. Khung chung (`components/Layout.tsx` sửa tại chỗ, không tạo shell thứ hai)

- Dải tiện ích trên cùng: hotline demo, "Hệ thống cửa hàng", đăng nhập/đăng ký hoặc tên khách.
- Header sticky: logo RetailSync + badge "Shop", **`SearchBox`**, nút vị trí (giữ `AddressModal`),
  **icon giỏ hàng + badge số món**.
- Nav danh mục ngang lấy từ `/api/categories`; bấm → `/danh-muc/:category`.
- Footer 3–4 cột tĩnh (giới thiệu, chính sách demo, liên hệ, phương thức thanh toán dự kiến).
- Trang nhân viên vẫn dùng khung này nhưng truyền `title`/`breadcrumbs` như hiện tại; không hiện
  nav shop ở `/stores*`.
- Token CSS (`styles/tokens.css`): thêm `--brand: #e31e24`, `--brand-hover`, `--brand-soft`,
  `--price`, giữ nguyên các token cũ để trang nhân viên không đổi màu.

### 6.2. Route

| Route | Trang | API |
|---|---|---|
| `/` | Trang chủ: banner, danh mục tròn, "Sản phẩm nổi bật" | `/api/shop/search?sort=sellable&limit=12`, `/api/categories` |
| `/tim-kiem?q=` | Kết quả tìm kiếm + sidebar lọc | `/api/shop/search` (đủ tham số) |
| `/danh-muc/:category` | Như trên, tiền lọc danh mục | `/api/shop/search?category=...` |
| `/san-pham/:sku` | Chi tiết sản phẩm (**mới**) | `/api/products/{sku}?latitude&longitude` |
| `/gio-hang` | Giỏ hàng + cửa hàng đủ hàng (**mới**) | `POST /api/cart/availability` |
| `/stores`, `/stores/:id`, `/stores/:id/products/:sku` | Nhân viên, giữ nguyên | như cũ |
| `/login`, `/register`, `/account` | Giữ nguyên | như cũ |

Route cũ `/stores/:storeId/products/:sku` **giữ** (nhân viên cần bảng lô); trang chi tiết shop mới
là `/san-pham/:sku`. Từ bảng nhân viên thêm link "Xem trang sản phẩm" trỏ sang route mới.

### 6.3. `SearchBox` (mới)

- Debounce 250 ms, gọi từ 2 ký tự, `AbortController` huỷ request cũ, cache 60 s theo `q`.
- Dropdown nhóm: Sản phẩm (ảnh 40×40, tên tô đậm phần khớp, giá, "Còn N tại <cửa hàng>"), Danh mục,
  "Tìm gần đây" (5 mục, localStorage, nút xoá), dòng cuối "Xem tất cả kết quả cho '<q>'".
- Bàn phím: ↑↓ di chuyển, Enter chọn, Esc đóng; `role="combobox"`, `aria-expanded`,
  `aria-activedescendant`, `aria-controls`; bấm ra ngoài đóng.
- Không gọi API khi focus rỗng; khi rỗng hiện "Tìm gần đây".

### 6.4. `FilterPanel` (thay `FilterBar`)

Một component, hai biến thể để không nhân bản logic:

| Biến thể | Dùng ở | Hình thức |
|---|---|---|
| `sidebar` | `/tim-kiem`, `/danh-muc/:c` | cột trái desktop; bottom-sheet "Bộ lọc (N)" trên mobile |
| `inline` | `/stores/:id` | thanh ngang như `FilterBar` hiện tại |

Nội dung sidebar:
1. **Danh mục**: checkbox nhiều lựa chọn + số đếm từ `facets.categories`, "Chọn tất cả"/"Bỏ chọn".
2. **Khoảng giá**: 4 nút preset (<20k, 20–50k, 50–100k, >100k) + 2 ô min/max; preset và ô đồng bộ nhau.
3. **Tình trạng**: "Chỉ còn hàng" (toggle), "Còn hàng trong bán kính 5 km" (toggle, chỉ bật khi có toạ độ).
4. **Sắp xếp** (dropdown riêng trên đầu kết quả): Liên quan / Tên A–Z / Giá thấp→cao / Giá cao→thấp / Bán chạy.
5. "Xoá tất cả" (chỉ bật khi có điều kiện khác mặc định).
6. Chip tóm tắt điều kiện đang bật phía trên lưới, mỗi chip có ×.

Toàn bộ state vẫn nằm trong URL (`lib/filters.ts`): `q`, `category` (nhiều lần), `price_min`,
`price_max`, `in_stock`, `near_km`, `sort`, `limit`, `offset`. `withFilterChange` reset `offset = 0`.

### 6.5. `ProductCard` (mới)

Ảnh 1:1 (fallback chữ cái như `ProductImage` hiện có), tên tối đa 2 dòng, danh mục nhỏ, giá lớn màu
`--price`, "Còn bán: N", dòng gợi ý cửa hàng gần nhất (`formatDistance` có sẵn, giữ nhãn "đường chim
bay" khi fallback), nút **Thêm vào giỏ** (stepper 1 → nút giỏ khi đã có trong giỏ). Toàn card là link
tới `/san-pham/:sku`, nút giỏ `stopPropagation`.

### 6.6. Trang chi tiết `/san-pham/:sku`

Bố cục 2 cột (desktop) / 1 cột (mobile):

- Trái: ảnh lớn (khung 1:1, viền nhẹ); dưới là 3 thumbnail **cùng một ảnh** — chỉ hiện khi
  `product_image` tồn tại (Phụ lục B); đợt này ẩn, không bịa ảnh.
- Phải: breadcrumb (Trang chủ / `<category>` / `<name>`), tên, `sku` + `barcode`, giá, tồn tổng
  "Còn N sản phẩm tại M cửa hàng", stepper số lượng, **Thêm vào giỏ**, nút "Xem giỏ hàng".
- Khối **"Còn hàng tại cửa hàng"**: mỗi dòng = tên, địa chỉ, khoảng cách, "còn N", "Hạn gần nhất";
  dòng gần nhất có nút "Mua tại đây" (thêm vào giỏ + gắn `preferred_store_id` trong giỏ để trang
  giỏ ưu tiên cửa hàng đó).
- Khối **"Lô hàng gần hết hạn"** chỉ hiện khi mở từ trang nhân viên (có `storeId`) — tận dụng
  `BatchTable` hiện có; ở route shop không hiện lô để không lộ chi tiết vận hành.
- **"Sản phẩm tương tự"**: lưới `ProductCard` từ `related`.
- Không có tab rỗng: mô tả/thành phần/thông số chưa có dữ liệu → không render tab (Phụ lục B mới
  thêm). Thay bằng khối "Thông tin" 2 cột: danh mục, mã vạch, quy cách (chưa có → bỏ dòng), bảo quản
  (chưa có → bỏ).

### 6.7. Trang giỏ `/gio-hang`

- Danh sách dòng: ảnh 64, tên (link), giá, stepper (1..99), nút xoá, cảnh báo "chỉ còn N" khi
  `available < requested` (lấy từ `availability`).
- Khối "Chọn cửa hàng lấy hàng": card cho từng cửa hàng trong `stores`, card `complete` đầu tiên
  được chọn sẵn; card không đủ hiện danh sách `missing` ("Thiếu: Bia Budweiser 330ml").
- Không cửa hàng nào đủ: banner "Không cửa hàng nào có đủ cả giỏ" + `split_plan` ("Đi 2 cửa hàng:
  Hải Châu lấy 2 món, Thanh Khê lấy 1 món") + nút "Vẫn tiếp tục" (khi luồng đặt hàng tồn tại).
- `unknown` SKU → banner "Một số sản phẩm không còn trong danh mục" + nút xoá khỏi giỏ.
- Tổng tiền (tính từ `unit_price` string bằng số nguyên đồng ở JS, không float), số món, nút
  "Tiến hành đặt hàng" — **disabled** kèm tooltip "Tính năng đặt hàng đang được phát triển" để
  không hứa tính năng chưa có.
- Giỏ rỗng: trạng thái rỗng + link về trang chủ.
- Giỏ lưu localStorage: `rts_cart_v1 = { items: [{sku, quantity, preferred_store_id?, added_at}],
  updatedAt }`; chỉ lưu `sku` + `quantity` + giá snapshot để hiển thị tạm, **luôn** đối chiếu lại
  giá/tên từ API khi mở giỏ (giá là dữ liệu máy chủ, không phải dữ liệu client).

### 6.8. Trạng thái & khả năng truy cập

- Mọi trang: loading (skeleton lưới/khối), rỗng, lỗi 503 có "Thử lại" (`StateBlock` hiện có).
- `aria-live="polite"` cho "N sản phẩm" và "Đã thêm vào giỏ".
- Focus chuyển tới `<h1>` khi đổi route (giữ hành vi Layout hiện tại).
- Ảnh có `alt` = tên sản phẩm; nút chỉ có icon có `aria-label`.
- Mobile 375 px: không tràn ngang, sidebar thành bottom-sheet, card 2 cột.

---

## 7. Bản đồ file (chỉ file mới/sửa, không có file bị xoá ngoài `FilterBar`)

```
api/app/
├─ queries/products.py            SỬA  thêm mảnh lọc dùng chung, chi tiết toàn cục, related
├─ queries/shop.py                SỬA  search_products nhận bộ lọc mới; bỏ nhánh cũ nếu trùng
├─ queries/availability.py        MỚI  tồn theo nhiều SKU + dựng stores/split_plan
├─ api/products.py                SỬA  thêm GET /products/{sku}
├─ api/shop.py                    SỬA  search mở rộng + GET /search/suggest
├─ api/cart.py                    MỚI  POST /cart/availability (chỉ đọc)
├─ api/stores.py                  SỬA  (nếu cần) không đổi hành vi
├─ schemas.py                     SỬA  ProductDetailGlobal, SuggestResponse, Availability*
├─ main.py                        SỬA  include_router(cart)
└─ tests/
   ├─ test_product_detail_api.py  MỚI
   ├─ test_search_filters_api.py  MỚI  (accent, giá, nhiều danh mục, facets, sort, phân trang)
   ├─ test_suggest_api.py         MỚI
   ├─ test_availability_api.py    MỚI
   └─ test_read_only.py           SỬA  thêm cart router vào danh sách router chỉ đọc

web/src/
├─ api/types.ts                   SỬA  + types mới, Filters mở rộng (category: string[])
├─ api/queries.ts                 SỬA  + useProductDetail, useSuggest, useAvailability
├─ lib/filters.ts                 SỬA  parse/serialize nhiều category, giá, sort mới
├─ lib/cart.tsx                   MỚI  CartProvider, useCart, localStorage, merge theo sku
├─ lib/normalize.ts               MỚI  bỏ dấu tiếng Việt (highlight + tìm gần đây)
├─ components/Layout.tsx          SỬA  header shop, nav danh mục, badge giỏ, footer
├─ components/SearchBox.tsx        MỚI  combobox gợi ý
├─ components/ProductCard.tsx      MỚI
├─ components/FilterPanel.tsx      MỚI  variant sidebar|inline (thay FilterBar)
├─ components/ProductGrid.tsx      MỚI  lưới + skeleton + empty
├─ components/QtyStepper.tsx       MỚI
├─ components/AddToCartButton.tsx  MỚI
├─ pages/HomePage.tsx              SỬA  banner + danh mục + lưới
├─ pages/CatalogPage.tsx           MỚI  /tim-kiem + /danh-muc/:category
├─ pages/ProductDetailPage.tsx     MỚI  /san-pham/:sku
├─ pages/CartPage.tsx              MỚI  /gio-hang
├─ components/FilterBar.tsx        XOÁ  (đã thay bằng FilterPanel inline)
├─ styles/tokens.css               SỬA  token thương hiệu
├─ styles/app.css                  SỬA  card, sidebar, drawer, banner, responsive
└─ App.tsx                         SỬA  route mới + CartProvider

web/tests/
├─ search-box.test.tsx             MỚI
├─ catalog-filters.test.tsx        MỚI
├─ product-detail.test.tsx         MỚI
└─ cart.test.tsx                   MỚI
```

Ghi chú: `web/tests/product-page.test.tsx` và `store-page.test.tsx` hiện có phải được cập nhật theo
`FilterPanel` mới — dự kiến sửa, không xoá.

---

## 8. Task thi công

| Phase | Việc | Ước lượng | Nghiệm thu |
|---|---|---|---|
| **0. Chốt hợp đồng** | Duyệt mục 4 (shape JSON), chốt `Filters` nhiều danh mục, chốt giỏ localStorage | 0.5 ngày | types.ts nháp khớp schemas.py nháp |
| **1. Tầng đọc mở rộng** | `queries/products.py` mảnh lọc chung + 4.1/4.5; `queries/shop.py` 4.2; `queries/availability.py`; schemas | 2.5 ngày | `pytest` cũ xanh; `GET /api/products/SKU-0001` trả đúng 3 cửa hàng demo; lọc giá/nhiều danh mục đúng |
| **2. Gợi ý + availability API** | `/api/search/suggest`, `POST /api/cart/availability`, router `cart.py`, cập nhật `test_read_only` | 1.5 ngày | "sua"→Sữa; giỏ 3 món 3 cửa hàng trả `best`/`split_plan` đúng; `test_read_only` xanh |
| **3. Khung shop + SearchBox** | `Layout` mới, nav danh mục, footer, token, `SearchBox`, `normalize.ts` | 2 ngày | Gõ 2 ký tự có dropdown, ↑↓/Enter/Esc, click ra ngoài đóng, không gọi API khi <2 ký tự |
| **4. Catalog + lọc** | `CatalogPage`, `FilterPanel`, `ProductGrid`, `ProductCard`, chip, phân trang, URL state | 3 ngày | Tick 2 danh mục + giá 20–50k + "còn hàng" + sort giá giảm → URL/back/forward đúng; số đếm facet khớp; mobile bottom-sheet |
| **5. Chi tiết sản phẩm** | `/san-pham/:sku`, khối cửa hàng còn hàng, related, thêm giỏ | 2 ngày | Mở trực tiếp bằng link/F5 đúng; 404 thân thiện; giá/tồn khớp API; related cùng danh mục |
| **6. Giỏ hàng** | `CartProvider`, badge, `/gio-hang`, stepper, `availability`, split_plan, empty state | 2 ngày | Thêm/xoá/đổi số lượng, F5 giữ giỏ; badge đúng; đủ/thiếu hàng hiển thị đúng; `unknown` SKU xử lý |
| **7. Trang chủ + đóng gói** | Banner, danh mục tròn, "nổi bật", responsive, a11y, cập nhật test cũ | 2 ngày | Trang chủ 12 card; 375 px không tràn; focus/aria đạt |
| **8. Kiểm thử + tài liệu** | Test mới, chạy toàn bộ, cập nhật `README.md` + `OVERVIEW.md` + `PLAN.md` dòng trạng thái | 2 ngày | `pytest` (API) xanh, `pnpm test`/`typecheck`/`lint` xanh; README có mục giỏ hàng + giới hạn |

Tổng **~15,5 ngày công**, 4 mốc: (0+1), (2+3), (4+5), (6+7+8).

---

## 9. Kiểm thử

**API (SQL Server test DB sẵn có `RTS_WEB_TEST` + fixture `seeded`)**

- Chi tiết: 404 SKU lạ; `stores` chỉ active; sắp theo khoảng cách; `sellable_quantity` tổng đúng;
  related cùng category, khác SKU, ≤8; không toạ độ → `distance_km = null`.
- Lọc: `sua` khớp "Sữa chua uống Yakult" (bài test collation); `%`/`_` không phải wildcard;
  nhiều `category` OR đúng; `price_min > price_max` → 422; `in_stock` loại sản phẩm chỉ có lô hết hạn;
  `near_km` loại cửa hàng xa; `sort=price_asc` dùng `unit_price` decimal, không string.
- Facets: tổng `count` danh mục (khi bỏ lọc danh mục) = `total`; bucket giá cộng lại = `total`.
- Phân trang: `total` là tổng sau lọc, không phải số dòng; `offset` vượt → mảng rỗng, không lỗi.
- Suggest: `q` 1 ký tự → 422; tối đa 8 sản phẩm; không trả `nearest` khi thiếu toạ độ.
- Availability: cửa hàng thiếu 1 món **không** `complete`; `best` là cửa hàng complete gần nhất;
  giỏ 1 món = hành vi `nearest`; `split_plan.store_count >= 2`; SKU lạ → `unknown`; 51 dòng → 422.
- Biên hạn dùng: lô hết hạn **đúng hôm nay** vẫn tính (dùng FIXED_TODAY như test hiện có).
- `test_read_only.py`: thêm `cart.py` vào router chỉ đọc; `COUNT(*)` 4 bảng không đổi sau khi gọi
  **cả** endpoint mới (đặc biệt `POST /api/cart/availability`).

**Web (Vitest + jsdom + msw, không cần DB)**

- `SearchBox`: debounce (fake timer), <2 ký tự không gọi API, ↑↓/Enter điều hướng đúng, Esc đóng.
- `FilterPanel`: tick danh mục → URL `category=A&category=B`; preset giá ghi `price_min/max`;
  "Xoá tất cả" reset; `inline` giữ hành vi cũ của `FilterBar`.
- `ProductCard`: giá format `32.000 ₫`, badge "hết hàng" khi 0, nút giỏ không điều hướng.
- `ProductDetailPage`: render đủ khối, ẩn khoảng cách khi `distance_km = null`, 404 → `StateBlock`.
- `CartPage`: 3 món 3 cửa hàng → card complete; không đủ → banner + `missing`; đổi số lượng cập nhật tổng.
- `CartProvider`: thêm trùng SKU cộng dồn; F5 đọc lại localStorage; dữ liệu hỏng → giỏ rỗng, không crash.
- `pnpm typecheck`, `pnpm lint` sạch.

**Không test:** pixel-perfect, e2e Playwright, OSRM thật (test trỏ cổng đóng như hiện tại).

---

## 10. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Collation accent-sensitive làm tìm "sua" trượt | Cao | `COLLATE Latin1_General_CI_AI` + test riêng; ghi ngưỡng xem lại ở README |
| `COLLATE` trong `LIKE` mất index seek | Trung bình | 21 SKU hiện tại; theo dõi thời gian phản hồi; Phụ lục B có phương án cột persisted |
| Mỗi lần lọc lại gọi OSRM → chậm | Trung bình | Chỉ gọi khi có toạ độ + `near_km`; 1 request/lần; timeout 2 s + fallback haversine; cache 60 s theo `(lat,lon)` |
| Facets lệch với danh sách | Trung bình | Facets tính bằng đúng mảnh lọc dùng chung, trừ chiều của chính nó; test đối chiếu tổng |
| Giỏ localStorage mất/không đồng bộ thiết bị | Trung bình | Ghi rõ trong README + UI ("giỏ lưu trên thiết bị này"); Phụ lục B có đường nâng cấp |
| Hai màn hình catalog cùng tồn tại | Trung bình | Xoá `FilterBar`, `ProductCard`/`FilterPanel` dùng chung, trang nhân viên qua `variant` |
| Người dùng thấy nút "đặt hàng" nhưng bấm không được | Trung bình | Nút disabled + tooltip "đang phát triển"; không tạo đơn giả |
| Đổi shape `/api/shop/search` làm gãy test/ UI cũ | Thấp | Chỉ **thêm** tham số + trường; `q`/`category`/`limit` cũ vẫn chạy; test cũ giữ xanh |
| Card ảnh 1:1 làm trang nặng | Thấp | Ảnh tĩnh đã có, `loading="lazy"`, `width/height` cố định |

---

## 11. Việc không làm trong đợt này

Không migration/bảng mới; không giữ hàng, không đặt đơn, không thanh toán; không đăng nhập bắt buộc
để mua; không giao hàng tận nhà; không rating/review; không banner động từ DB; không đa ngôn ngữ;
không full-text engine; không sửa `middleware/`.

---

## Phụ lục A — Vì sao bám bố cục chứ không sao chép WinMart

winmart.vn là SPA; nội dung chỉ render sau JavaScript nên không đọc được markup tĩnh. Kế hoạch bám
**cấu trúc** (header + search + banner + card + sidebar lọc + chi tiết + giỏ) chứ không sao chép
nhãn hiệu, logo, ảnh hay nội dung. Màu đỏ `#e31e24` dùng như màu CTA của shop RetailSync, thương
hiệu vẫn là RetailSync.

---

## Phụ lục B — Kế hoạch tương lai (chưa làm, chưa thêm bảng)

Giữ nguyên đặc tả để lần sau chỉ cần thi công, không phải thiết kế lại.

### B.1. Làm giàu chi tiết sản phẩm — `database/migrations/006+`

```sql
-- 006_product_detail.sql
ALTER TABLE dbo.product ADD
    slug varchar(200) NULL, brand nvarchar(80) NULL, unit_label nvarchar(40) NULL,
    origin nvarchar(80) NULL, short_description nvarchar(400) NULL,
    description nvarchar(max) NULL, ingredients nvarchar(1000) NULL,
    storage_note nvarchar(400) NULL, is_active bit NOT NULL DEFAULT 1,
    created_at datetime2 NOT NULL DEFAULT SYSUTCDATETIME();
CREATE UNIQUE INDEX uq_product_slug ON dbo.product(slug) WHERE slug IS NOT NULL;

-- 007_product_gallery.sql   dbo.product_image(image_id, sku, url, alt_text, sort_order)
-- 008_category.sql          dbo.category(category_id, slug, name, parent_id, sort_order) + product.category_id
-- 009_promotion.sql         dbo.promotion + dbo.promotion_product(promotion_id, sku, promo_price, max_qty)
-- 010_product_spec.sql      dbo.product_spec(sku, name, value, sort_order)
```

Khi đó trang chi tiết bật lại: tab Mô tả/Thành phần/Bảo quản/Thông số, gallery nhiều ảnh, giá gạch
+ badge giảm giá, filter Thương hiệu + "Đang khuyến mãi", `related` theo thương hiệu.
Điều kiện tiên quyết: nhóm đồng ý thêm SKU/seed và chấp nhận cập nhật
`scripts/demo/sprint2_smoke.py` (đã từng lệch 9→14, xem `OVERVIEW.md` mục 7.1).

### B.2. Giỏ hàng phía máy chủ + giữ hàng + thanh toán

Bảng trong `RTS_CUSTOMER` (DDL trong `customer_db.py`, **nên** thêm bảng `schema_version` trước):

| Bảng | Cột chính |
|---|---|
| `cart` | `cart_id`, `customer_id NULL`, `anon_token_hash char(64) NULL`, `status`, `created_at`, `updated_at` |
| `cart_item` | `cart_id`, `sku`, `quantity`, `unit_price_snapshot`, `preferred_store_id NULL`, `UNIQUE(cart_id, sku)` |
| `customer_order` | `order_id`, `order_code`, `customer_id`, `store_id`, `status`, `subtotal`, `total`, `pickup_at`, `payment_method`, `payment_status`, `idempotency_key`, `UNIQUE(customer_id, idempotency_key)` |
| `order_item` | `order_id`, `sku`, `name_snapshot`, `quantity`, `unit_price`, `line_total` |
| `stock_hold` | `hold_id`, `order_id`, `store_id`, `sku`, `quantity`, `status (HELD/CONFIRMED/RELEASED/EXPIRED)`, `expires_at` |
| `payment` | `payment_id`, `order_id`, `provider`, `provider_ref`, `amount`, `status`, `paid_at` |
| `order_event` | `order_id`, `from_status`, `to_status`, `at`, `note` |

Luồng: `POST /api/orders` (chọn store, `pickup_at`, `Idempotency-Key`) → tạo `stock_hold` 15 phút →
`POST /api/orders/{id}/pay` (mock) → `PAID`/hold `CONFIRMED` → job 60 s trong `lifespan` chuyển hold
quá hạn sang `EXPIRED` → `POST /api/orders/{id}/cancel` giải phóng hold. Tồn hiển thị khi đó là
`available = sellable − held`.

**Giới hạn phải nói rõ với người dùng:** hold nằm ngoài store DB nên POS vẫn bán được món đó — đây là
"giữ chỗ mềm", nhân viên xác nhận lại khi khách đến. Muốn trừ tồn thật thì phải thêm endpoint
reservation vào `middleware/` theo `openapi.yaml` (việc của nhóm, ngoài phạm vi app này).

### B.3. Đường nâng cấp giỏ hiện tại

`lib/cart.tsx` chỉ là lớp lưu trữ. Khi có bảng `cart`: giữ nguyên `useCart()` API, đổi phần đọc/ghi
sang `GET/POST /api/cart`, thêm bước merge `anon_token` → `customer_id` sau đăng nhập. Không phải
sửa `CartPage`, `ProductCard`, `Layout`.

### B.4. Khi catalog lớn

Thay `COLLATE` trong `LIKE` bằng cột persisted `search_text COLLATE Latin1_General_CI_AI` + index
(DDL nháp ở kế hoạch trước), hoặc SQL Server FULLTEXT. Ngưỡng đề xuất: ~50.000 SKU.
