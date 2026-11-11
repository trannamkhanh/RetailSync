import type { Filters, SortKey } from '../api/types'

export const DEFAULT_LIMIT = 25

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'name', label: 'Tên' },
  { value: 'price', label: 'Giá' },
  { value: 'sellable', label: 'Còn bán' },
]

export function defaultFilters(): Filters {
  return { q: '', category: '', inStock: false, sort: 'name', limit: DEFAULT_LIMIT, offset: 0 }
}

function sortKey(raw: string | null): SortKey {
  return raw === 'price' || raw === 'sellable' || raw === 'name' ? raw : 'name'
}

function positiveInt(raw: string | null, fallback: number, max: number): number {
  if (raw === null || raw === '') return fallback
  const value = Number(raw)
  if (!Number.isInteger(value) || value < 1 || value > max) return fallback
  return value
}

export function parseFilters(search: URLSearchParams): Filters {
  const offset = Number(search.get('offset') ?? '0')
  return {
    q: (search.get('q') ?? '').slice(0, 100),
    category: (search.get('category') ?? '').slice(0, 50),
    inStock: search.get('in_stock') === 'true',
    sort: sortKey(search.get('sort')),
    limit: positiveInt(search.get('limit'), DEFAULT_LIMIT, 200),
    offset: Number.isInteger(offset) && offset >= 0 ? offset : 0,
  }
}

export function serializeFilters(filters: Filters): URLSearchParams {
  const search = new URLSearchParams()
  if (filters.q) search.set('q', filters.q)
  if (filters.category) search.set('category', filters.category)
  if (filters.inStock) search.set('in_stock', 'true')
  if (filters.sort !== 'name') search.set('sort', filters.sort)
  if (filters.limit !== DEFAULT_LIMIT) search.set('limit', String(filters.limit))
  if (filters.offset > 0) search.set('offset', String(filters.offset))
  return search
}

export function withFilterChange(filters: Filters, change: Partial<Filters>): Filters {
  return { ...filters, ...change, offset: 0 }
}
