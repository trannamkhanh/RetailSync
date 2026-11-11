import type { Product, StoreCard, StoreDetail } from '../api/types'

export const STORES: StoreCard[] = [
  { store_id: 'STORE-DN1', name: 'Cửa hàng Hải Châu', region_id: 'DN', address_text: '123 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, Đà Nẵng', product_count: 9, sellable_units: 360 },
  { store_id: 'STORE-DN2', name: 'Cửa hàng Thanh Khê', region_id: 'DN', address_text: '456 Nguyễn Văn Linh, Phường Tân Chính, Quận Thanh Khê, Đà Nẵng', product_count: 9, sellable_units: 225 },
  { store_id: 'STORE-DN3', name: 'Cửa hàng Sơn Trà', region_id: 'DN', address_text: '789 Ngô Quyền, Phường An Hải Bắc, Quận Sơn Trà, Đà Nẵng', product_count: 9, sellable_units: 135 },
]

export const STORE_DETAIL: StoreDetail = {
  ...STORES[0],
  expired_units: 0,
}

export const CATEGORIES = ['Bakery', 'Dairy', 'Dry goods']

/**
 * Nine products like the seed. SKU-0004 has an expired batch and a batch that
 * expires today (still sellable), and SKU-0006 has nothing sellable at all.
 *
 * ``nearest_store`` is filled in below the array: most rows are sold by the
 * store being viewed, SKU-0006 has nothing anywhere, and SKU-0007 is stocked
 * only by another branch, which is the "go to the other store" case.
 */
const PRODUCT_ROWS: Omit<Product, 'nearest_store'>[] = [
  {
    sku: 'SKU-0001',
    barcode: '8930000000011',
    name: 'Fresh milk 1L',
    category: 'Dairy',
    unit_price: '32000.00',
    image_url: '/products/fresh-milk.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0001-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0001-2', expiry_date: '2026-11-30', quantity: 24, sellable: true },
    ],
  },
  {
    sku: 'SKU-0002',
    barcode: '8930000000028',
    name: 'Yogurt 100g',
    category: 'Dairy',
    unit_price: '7000.00',
    image_url: '/products/yogurt.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0002-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0002-2', expiry_date: '2026-11-30', quantity: 24, sellable: true },
    ],
  },
  {
    sku: 'SKU-0003',
    barcode: '8930000000035',
    name: 'Cheese slices 200g',
    category: 'Dairy',
    unit_price: '65000.00',
    image_url: '/products/cheese.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0003-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0003-2', expiry_date: '2026-11-30', quantity: 24, sellable: true },
    ],
  },
  {
    sku: 'SKU-0004',
    barcode: '8930000000042',
    name: 'Bread 400g',
    category: 'Bakery',
    unit_price: '25000.00',
    image_url: '/products/bread.jpg',
    quantity: 40,
    sellable_quantity: 25,
    expired_quantity: 15,
    nearest_expiry: '2026-11-10',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0004-0', expiry_date: '2026-11-09', quantity: 15, sellable: false },
      { batch_id: 'B-STORE-DN1-SKU-0004-1', expiry_date: '2026-11-10', quantity: 25, sellable: true },
    ],
  },
  {
    sku: 'SKU-0005',
    barcode: '8930000000059',
    name: 'Sponge cake 300g',
    category: 'Bakery',
    unit_price: '45000.00',
    image_url: '/products/sponge-cake.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0005-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0005-2', expiry_date: '2026-11-20', quantity: 24, sellable: true },
    ],
  },
  {
    sku: 'SKU-0006',
    barcode: '8930000000066',
    name: 'Butter cookies 200g',
    category: 'Bakery',
    unit_price: '38000.00',
    image_url: '/products/butter-cookies.jpg',
    quantity: 20,
    sellable_quantity: 0,
    expired_quantity: 20,
    nearest_expiry: null,
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0006-0', expiry_date: '2026-11-01', quantity: 20, sellable: false },
    ],
  },
  {
    sku: 'SKU-0007',
    barcode: '8930000000073',
    name: 'Rice 50kg',
    category: 'Dry goods',
    unit_price: '1250000.00',
    image_url: '/products/rice.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0007-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0007-2', expiry_date: '2027-05-09', quantity: 24, sellable: true },
    ],
  },
  {
    sku: 'SKU-0008',
    barcode: '8930000000080',
    name: 'Instant noodles 75g',
    category: 'Dry goods',
    unit_price: '4500.00',
    image_url: '/products/instant-noodles.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0008-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0008-2', expiry_date: '2027-05-09', quantity: 24, sellable: true },
    ],
  },
  {
    sku: 'SKU-0009',
    barcode: '8930000000097',
    name: 'Cooking oil 1L',
    category: 'Dry goods',
    unit_price: '58000.00',
    image_url: '/products/cooking-oil.jpg',
    quantity: 40,
    sellable_quantity: 40,
    expired_quantity: 0,
    nearest_expiry: '2026-11-13',
    batches: [
      { batch_id: 'B-STORE-DN1-SKU-0009-1', expiry_date: '2026-11-13', quantity: 16, sellable: true },
      { batch_id: 'B-STORE-DN1-SKU-0009-2', expiry_date: '2027-05-09', quantity: 24, sellable: true },
    ],
  },
]

/** The other branch, used when a product is not sold by the store being viewed. */
const OTHER_STORE = {
  store_id: 'STORE-DN2',
  name: 'Cửa hàng Thanh Khê',
  region_id: 'DN',
  address_text: '456 Nguyễn Văn Linh, Phường Tân Chính, Quận Thanh Khê, Đà Nẵng',
  sellable_quantity: 25,
  distance_km: 4.9,
  distance_kind: 'road' as const,
}

function nearestFor(row: Omit<Product, 'nearest_store'>): Product['nearest_store'] {
  if (row.sku === 'SKU-0006') return null
  if (row.sku === 'SKU-0007') return { ...OTHER_STORE, sellable_quantity: row.sellable_quantity }
  return {
    store_id: 'STORE-DN1',
    name: 'Cửa hàng Hải Châu',
    region_id: 'DN',
    address_text: '123 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, Đà Nẵng',
    sellable_quantity: row.sellable_quantity,
    distance_km: 0,
    distance_kind: 'road' as const,
  }
}

export const PRODUCTS: Product[] = PRODUCT_ROWS.map((row) => ({
  ...row,
  nearest_store: nearestFor(row),
}))

export function productPage(items: Product[] = PRODUCTS, total = items.length) {
  return { store_id: 'STORE-DN1', total, limit: 25, offset: 0, items }
}

export const SAMPLE_ADDRESSES = [
  {
    address_id: 'ADR-HAI-CHAU',
    label: 'Hải Châu, Đà Nẵng',
    address_text: 'Đường Bạch Đằng, Hải Châu, Đà Nẵng',
    latitude: 16.0678,
    longitude: 108.2208,
  },
  {
    address_id: 'ADR-SON-TRA',
    label: 'Sơn Trà, Đà Nẵng',
    address_text: 'Đường Ngô Quyền, Sơn Trà, Đà Nẵng',
    latitude: 16.075,
    longitude: 108.235,
  },
]

export const SAVED_ADDRESSES = [
  {
    address_id: 'SAVED-1',
    label: 'Nhà riêng',
    address_text: '123 Bạch Đằng, Hải Châu',
    latitude: 16.0678,
    longitude: 108.2208,
  },
]

export const STORE_SUGGESTION = {
  store_id: 'STORE-DN1',
  name: 'Cửa hàng Hải Châu',
  region_id: 'DN',
  address_text: '123 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, Đà Nẵng',
  sellable_quantity: 40,
  distance_km: 0.2,
  distance_kind: 'road' as const,
}

/** Search results shaped like the shop API: each product points at its nearest store. */
export const SHOP_SEARCH_ITEMS = [
  {
    sku: 'SKU-0001',
    barcode: '8930000000011',
    name: 'Fresh milk 1L',
    category: 'Dairy',
    unit_price: '32000.00',
    image_url: '/products/fresh-milk.jpg',
    stores: [STORE_SUGGESTION],
    nearest: STORE_SUGGESTION,
  },
  {
    sku: 'SKU-0006',
    barcode: '8930000000066',
    name: 'Butter cookies 200g',
    category: 'Bakery',
    unit_price: '38000.00',
    image_url: '/products/butter-cookies.jpg',
    stores: [],
    nearest: null,
  },
]

