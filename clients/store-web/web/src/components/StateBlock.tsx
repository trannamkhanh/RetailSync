import { ApiError } from '../api/client'

type StateKind = 'loading' | 'empty' | 'error'

interface StateBlockProps {
  kind: StateKind
  title?: string
  message?: string
  error?: unknown
  onRetry?: () => void
}

function errorText(error: unknown): { title: string; detail: string } {
  if (error instanceof ApiError) {
    if (error.code === 'STORE_WEB_UNAVAILABLE' || error.status === 503) {
      return {
        title: 'Không kết nối được cơ sở dữ liệu',
        detail: 'Máy chủ chưa đọc được dữ liệu. Kiểm tra SQL Server rồi thử lại.',
      }
    }
    if (error.status === 404) {
      return { title: 'Không tìm thấy dữ liệu', detail: error.message }
    }
    if (error.status === 422) {
      return {
        title: 'Bộ lọc không hợp lệ',
        detail: 'Tham số trên đường dẫn không đúng. Xoá bộ lọc rồi thử lại.',
      }
    }
    return { title: 'Không tải được dữ liệu', detail: error.message }
  }
  return {
    title: 'Không tải được dữ liệu',
    detail: 'Đã xảy ra lỗi không xác định. Thử lại sau.',
  }
}

/** The three states every data screen needs: loading, empty, and error with retry. */
export function StateBlock({ kind, title, message, error, onRetry }: StateBlockProps) {
  if (kind === 'loading') {
    return (
      <div className="state" role="status" aria-busy="true" aria-live="polite">
        <p className="state__title">{title ?? 'Đang tải…'}</p>
        <div className="skeleton-row" />
        <div className="skeleton-row" />
        <div className="skeleton-row" />
        <div className="skeleton-row" />
        <div className="skeleton-row" />
      </div>
    )
  }

  if (kind === 'empty') {
    return (
      <div className="state" role="status">
        <p className="state__title">{title ?? 'Không có dữ liệu'}</p>
        {message && <p className="state__detail">{message}</p>}
      </div>
    )
  }

  const text = errorText(error)
  return (
    <div className="state state--error" role="alert">
      <p className="state__title">{title ?? text.title}</p>
      <p className="state__detail">{message ?? text.detail}</p>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          Thử lại
        </button>
      )}
    </div>
  )
}
