import type { Filters } from '../api/types'
import { formatCount } from '../lib/format'

interface PaginationProps {
  total: number
  filters: Filters
  shown: number
  onChange: (offset: number) => void
}

/** Previous/next paging that keeps every other filter in place. */
export function Pagination({ total, filters, shown, onChange }: PaginationProps) {
  if (total === 0) return null

  const first = filters.offset + 1
  const last = filters.offset + shown
  const canPrevious = filters.offset > 0
  const canNext = filters.offset + filters.limit < total

  return (
    <nav className="pagination" aria-label="Phân trang">
      <button
        type="button"
        className="btn"
        disabled={!canPrevious}
        onClick={() => onChange(Math.max(0, filters.offset - filters.limit))}
      >
        Trước
      </button>
      <span className="pagination__status">
        {formatCount(first)}–{formatCount(last)} / {formatCount(total)} sản phẩm
      </span>
      <button
        type="button"
        className="btn"
        disabled={!canNext}
        onClick={() => onChange(filters.offset + filters.limit)}
      >
        Sau
      </button>
    </nav>
  )
}
