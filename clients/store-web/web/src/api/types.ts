export interface Batch {
  batch_id: string
  expiry_date: string
  quantity: number
  sellable: boolean
}

export interface Product {
  sku: string
  barcode: string
  name: string
  category: string
  unit_price: string
  image_url: string | null
  quantity: number
  sellable_quantity: number
  expired_quantity: number
  nearest_expiry: string | null
  batches: Batch[]
  nearest_store: StoreSuggestion | null
}

export interface StoreCard {
  store_id: string
  name: string
  region_id: string
  address_text: string | null
  product_count: number
  sellable_units: number
}

export interface StoreDetail extends StoreCard {
  expired_units: number
}

export interface StoreList {
  stores: StoreCard[]
}

export interface ProductPage {
  store_id: string
  total: number
  limit: number
  offset: number
  items: Product[]
}

export interface ProductDetail {
  store_id: string
  item: Product
}

export interface Categories {
  categories: string[]
}

export type SortKey = 'name' | 'price' | 'sellable'

export interface Filters {
  q: string
  category: string
  inStock: boolean
  sort: SortKey
  limit: number
  offset: number
}

// --- Customer Shop Types ---

export interface CustomerProfile {
  customer_id: number
  email: string
  full_name: string
}

export interface AuthSession {
  customer: CustomerProfile
}

export interface AddressItem {
  address_id: string
  label: string
  address_text: string
  latitude: number
  longitude: number
}

export interface AddressList {
  addresses: AddressItem[]
}

export type DistanceKind = 'road' | 'straight'

export interface StoreSuggestion {
  store_id: string
  name: string
  region_id: string
  address_text: string | null
  sellable_quantity: number
  distance_km: number
  distance_kind: DistanceKind
}

export interface ShopProduct {
  sku: string
  barcode: string
  name: string
  category: string
  unit_price: string
  image_url: string | null
  stores: StoreSuggestion[]
  nearest: StoreSuggestion | null
}

export interface ShopSearch {
  q: string
  latitude: number
  longitude: number
  total: number
  items: ShopProduct[]
}
