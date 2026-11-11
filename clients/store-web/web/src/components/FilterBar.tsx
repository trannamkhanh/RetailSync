import { useEffect, useRef, useState } from 'react'

import type { Filters, SortKey } from '../api/types'
import { SORT_OPTIONS, withFilterChange } from '../lib/filters'

interface FilterBarProps {
  filters: Filters
  categories: string[]
  onChange: (filters: Filters) => void
  onReset: () => void
}

/**
 * q, category, in-stock and sort. Every change resets the page offset to 0.
 *
 * The text box keeps its own value while the user types and sends the new
 * query after 300 ms. When the URL query changes from the outside (back button,
 * "Xoá lọc"), the box shows that value again.
 */
export function FilterBar({ filters, categories, onChange, onReset }: FilterBarProps) {
  const [draft, setDraft] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const value = draft ?? filters.q

  function changeQuery(next: string) {
    setDraft(next)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      setDraft(null)
      if (next !== filters.q) onChange(withFilterChange(filters, { q: next }))
    }, 300)
  }

  function submit(next: string) {
    window.clearTimeout(timer.current)
    setDraft(null)
    if (next !== filters.q) onChange(withFilterChange(filters, { q: next }))
  }

  const dirty =
    filters.q !== '' || filters.category !== '' || filters.inStock || filters.sort !== 'name'

  return (
    <form
      className="filter-bar"
      role="search"
      onSubmit={(event) => {
        event.preventDefault()
        submit(value)
      }}
    >
      <label>
        <span className="sr-only">Tìm theo tên hoặc SKU</span>
        <input
          type="search"
          value={value}
          maxLength={100}
          placeholder="Tìm theo tên hoặc SKU"
          onChange={(event) => changeQuery(event.target.value)}
        />
      </label>

      <label>
        <span>Danh mục</span>
        <select
          value={filters.category}
          onChange={(event) => onChange(withFilterChange(filters, { category: event.target.value }))}
        >
          <option value="">Tất cả</option>
          {categories.map((category) => (
            <option key={category} value={category}>
              {category}
            </option>
          ))}
        </select>
      </label>

      <label>
        <input
          type="checkbox"
          checked={filters.inStock}
          onChange={(event) => onChange(withFilterChange(filters, { inStock: event.target.checked }))}
        />
        <span>Chỉ còn hàng</span>
      </label>

      <label>
        <span>Sắp xếp</span>
        <select
          value={filters.sort}
          onChange={(event) =>
            onChange(withFilterChange(filters, { sort: event.target.value as SortKey }))
          }
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        className="btn"
        onClick={() => {
          setDraft(null)
          onReset()
        }}
        disabled={!dirty}
      >
        Xoá lọc
      </button>
    </form>
  )
}
