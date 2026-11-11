import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { apiDelete, apiGet, apiPost } from './client'
import type {
  AddressItem,
  AddressList,
  AuthSession,
  Categories,
  Filters,
  ProductDetail,
  ProductPage,
  ShopSearch,
  StoreDetail,
  StoreList,
} from './types'

export const queryKeys = {
  stores: ['stores'] as const,
  store: (storeId: string) => ['store', storeId] as const,
  categories: ['categories'] as const,
  products: (storeId: string, filters: Filters, lat?: number, lon?: number) =>
    ['products', storeId, filters, lat, lon] as const,
  product: (storeId: string, sku: string, includeEmpty: boolean) =>
    ['product', storeId, sku, includeEmpty] as const,
  me: ['auth', 'me'] as const,
  sampleAddresses: ['shop', 'addresses'] as const,
  myAddresses: ['shop', 'addresses', 'mine'] as const,
  shopSearch: (q: string, lat: number, lon: number, cat?: string) =>
    ['shop', 'search', q, lat, lon, cat] as const,
}

// --- Store Management Queries ---

export function useStores() {
  return useQuery({
    queryKey: queryKeys.stores,
    queryFn: () => apiGet<StoreList>('/api/stores'),
  })
}

export function useStore(storeId: string) {
  return useQuery({
    queryKey: queryKeys.store(storeId),
    queryFn: () => apiGet<StoreDetail>(`/api/stores/${encodeURIComponent(storeId)}`),
    enabled: Boolean(storeId),
  })
}

export function useCategories() {
  return useQuery({
    queryKey: queryKeys.categories,
    queryFn: () => apiGet<Categories>('/api/categories'),
    staleTime: 5 * 60_000,
  })
}

export function useProducts(
  storeId: string,
  filters: Filters,
  latitude?: number,
  longitude?: number,
) {
  const hasCoords = typeof latitude === 'number' && typeof longitude === 'number'
  return useQuery({
    queryKey: queryKeys.products(storeId, filters, hasCoords ? latitude : undefined, hasCoords ? longitude : undefined),
    queryFn: () =>
      apiGet<ProductPage>(`/api/stores/${encodeURIComponent(storeId)}/products`, {
        q: filters.q,
        category: filters.category,
        in_stock: filters.inStock ? true : undefined,
        sort: filters.sort,
        limit: filters.limit,
        offset: filters.offset,
        latitude: hasCoords ? latitude : undefined,
        longitude: hasCoords ? longitude : undefined,
      }),
    enabled: Boolean(storeId),
    placeholderData: keepPreviousData,
  })
}

export function useProduct(storeId: string, sku: string, includeEmpty = false) {
  return useQuery({
    queryKey: queryKeys.product(storeId, sku, includeEmpty),
    queryFn: () =>
      apiGet<ProductDetail>(
        `/api/stores/${encodeURIComponent(storeId)}/products/${encodeURIComponent(sku)}`,
        { include_empty: includeEmpty ? true : undefined },
      ),
    enabled: Boolean(storeId) && Boolean(sku),
  })
}

// --- Customer Auth & Shop Queries ---

export function useAuth() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => apiGet<AuthSession>('/api/auth/me'),
    retry: false,
    staleTime: 60_000,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiPost<AuthSession>('/api/auth/login', body),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.me, data)
      qc.invalidateQueries({ queryKey: queryKeys.myAddresses })
    },
  })
}

export function useRegister() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { email: string; full_name: string; password: string }) =>
      apiPost<AuthSession>('/api/auth/register', body),
    onSuccess: (data) => {
      qc.setQueryData(queryKeys.me, data)
      qc.invalidateQueries({ queryKey: queryKeys.myAddresses })
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => apiPost('/api/auth/logout'),
    onSuccess: () => {
      qc.setQueryData(queryKeys.me, null)
      qc.removeQueries({ queryKey: queryKeys.myAddresses })
    },
  })
}

export function useSampleAddresses() {
  return useQuery({
    queryKey: queryKeys.sampleAddresses,
    queryFn: () => apiGet<AddressList>('/api/shop/addresses'),
    staleTime: 10 * 60_000,
  })
}

export function useMyAddresses(isLoggedIn: boolean) {
  return useQuery({
    queryKey: queryKeys.myAddresses,
    queryFn: () => apiGet<AddressList>('/api/shop/addresses/mine'),
    enabled: isLoggedIn,
  })
}

export function useSaveAddress() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { label: string; address_text: string; latitude: number; longitude: number }) =>
      apiPost<AddressItem>('/api/shop/addresses/mine', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.myAddresses })
    },
  })
}

export function useDeleteAddress() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (addressId: string) => apiDelete(`/api/shop/addresses/mine/${encodeURIComponent(addressId)}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.myAddresses })
    },
  })
}

export function useShopSearch(q: string, lat?: number, lon?: number, category?: string) {
  const hasCoords = typeof lat === 'number' && typeof lon === 'number'
  return useQuery({
    queryKey: queryKeys.shopSearch(q, lat ?? 0, lon ?? 0, category),
    queryFn: () =>
      apiGet<ShopSearch>('/api/shop/search', {
        // The API requires a non-empty q; whitespace means "no keyword" and it
        // returns the whole catalog.
        q: q.trim() ? q.trim() : ' ',
        latitude: lat,
        longitude: lon,
        category: category || undefined,
      }),
    enabled: hasCoords,
    placeholderData: keepPreviousData,
  })
}
