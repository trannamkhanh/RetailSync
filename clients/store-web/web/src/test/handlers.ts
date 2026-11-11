import { http, HttpResponse } from 'msw'

import {
  CATEGORIES,
  PRODUCTS,
  SAMPLE_ADDRESSES,
  SAVED_ADDRESSES,
  SHOP_SEARCH_ITEMS,
  STORE_DETAIL,
  STORES,
  productPage,
} from './fixtures'

/** The happy-path API used by most tests; individual tests override as needed. */
export const handlers = [
  // --- Store inspection (internal) ---
  http.get('/api/stores', () => HttpResponse.json({ stores: STORES })),

  http.get('/api/stores/:storeId', ({ params }) => {
    if (params.storeId !== STORE_DETAIL.store_id) {
      return HttpResponse.json(
        { outcome: 'REJECTED', code: 'NOT_FOUND', message: 'Store does not exist.' },
        { status: 404 },
      )
    }
    return HttpResponse.json(STORE_DETAIL)
  }),

  http.get('/api/categories', () => HttpResponse.json({ categories: CATEGORIES })),

  http.get('/api/stores/:storeId/products', ({ request }) => {
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') ?? '').toLowerCase()
    const category = url.searchParams.get('category') ?? ''
    const inStock = url.searchParams.get('in_stock') === 'true'

    let items = PRODUCTS
    if (q) {
      items = items.filter(
        (item) => item.name.toLowerCase().includes(q) || item.sku.toLowerCase().includes(q),
      )
    }
    if (category) items = items.filter((item) => item.category === category)
    if (inStock) items = items.filter((item) => item.sellable_quantity > 0)

    return HttpResponse.json(productPage(items))
  }),

  http.get('/api/stores/:storeId/products/:sku', ({ params }) => {
    const item = PRODUCTS.find((product) => product.sku === params.sku)
    if (!item) {
      return HttpResponse.json(
        { outcome: 'REJECTED', code: 'NOT_FOUND', message: 'Product does not exist.' },
        { status: 404 },
      )
    }
    return HttpResponse.json({ store_id: params.storeId, item })
  }),

  // --- Customer auth ---
  http.get('/api/auth/me', () =>
    HttpResponse.json(
      { outcome: 'REJECTED', code: 'UNAUTHENTICATED', message: 'Chưa đăng nhập.' },
      { status: 401 },
    ),
  ),

  http.post('/api/auth/login', () =>
    HttpResponse.json({ customer: { customer_id: 1, email: 'a@b.test', full_name: 'Khách Test' } }),
  ),

  http.post('/api/auth/register', () =>
    HttpResponse.json(
      { customer: { customer_id: 2, email: 'new@b.test', full_name: 'Khách Mới' } },
      { status: 201 },
    ),
  ),

  http.post('/api/auth/logout', () => new HttpResponse(null, { status: 204 })),

  // --- Customer shop ---
  http.get('/api/shop/addresses', () => HttpResponse.json({ addresses: SAMPLE_ADDRESSES })),

  http.get('/api/shop/addresses/mine', ({ request }) => {
    if (!request.headers.get('Cookie')) {
      return HttpResponse.json(
        { outcome: 'REJECTED', code: 'UNAUTHENTICATED', message: 'Chưa đăng nhập.' },
        { status: 401 },
      )
    }
    return HttpResponse.json({ addresses: SAVED_ADDRESSES })
  }),

  http.post('/api/shop/addresses/mine', () =>
    HttpResponse.json(
      {
        address_id: 'SAVED-9',
        label: 'Địa chỉ mới',
        address_text: 'Nguyễn Huệ, Đà Nẵng',
        latitude: 16.06,
        longitude: 108.22,
      },
      { status: 201 },
    ),
  ),

  http.delete('/api/shop/addresses/mine/:addressId', () => new HttpResponse(null, { status: 204 })),

  http.get('/api/shop/search', ({ request }) => {
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') ?? '').trim().toLowerCase()
    const category = url.searchParams.get('category') ?? ''

    let items = SHOP_SEARCH_ITEMS
    if (q) {
      items = items.filter(
        (item) => item.name.toLowerCase().includes(q) || item.sku.toLowerCase().includes(q),
      )
    }
    if (category) items = items.filter((item) => item.category === category)

    return HttpResponse.json({
      q,
      latitude: Number(url.searchParams.get('latitude')),
      longitude: Number(url.searchParams.get('longitude')),
      total: items.length,
      items,
    })
  }),
]
