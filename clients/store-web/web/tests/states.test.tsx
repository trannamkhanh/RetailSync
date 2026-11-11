import { QueryClient } from '@tanstack/react-query'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { ApiError } from '../src/api/client'
import { server } from '../src/test/server'
import { renderRoute } from './testUtils'

function staticClient(): QueryClient {
  // No retries, so a test sees the first failure immediately.
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500),
      },
    },
  })
}

describe('states', () => {
  it('shows an empty message, not an error, when nothing matches', async () => {
    renderRoute('/stores/STORE-DN1?q=zzz-no-match')
    expect(await screen.findByText('Không có sản phẩm khớp bộ lọc.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('turns an unknown store into a clear heading with a way back', async () => {
    renderRoute('/stores/STORE-XX')
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Không tìm thấy cửa hàng' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Về danh sách cửa hàng/ })).toHaveAttribute(
      'href',
      '/stores',
    )
  })

  it('offers retry when the database is unavailable', async () => {
    const user = userEvent.setup()
    let fail = true
    server.use(
      http.get('/api/stores', () => {
        if (fail) {
          return HttpResponse.json(
            { outcome: 'ERROR', code: 'STORE_WEB_UNAVAILABLE', message: 'Service unavailable.' },
            { status: 503 },
          )
        }
        return HttpResponse.json({ stores: [] })
      }),
    )

    renderRoute('/stores', new QueryClient({ defaultOptions: { queries: { retry: false } } }))
    expect(await screen.findByText('Không kết nối được cơ sở dữ liệu')).toBeInTheDocument()

    fail = false
    await user.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByText('Chưa có cửa hàng nào đang hoạt động.')).toBeInTheDocument()
  })

  it('uses one generic message for a 422 without leaking raw JSON', async () => {
    server.use(
      http.get('/api/stores/:storeId/products', () =>
        HttpResponse.json(
          {
            outcome: 'REJECTED',
            code: 'VALIDATION_ERROR',
            message: "Invalid field 'sort': Input should be 'name', 'price' or 'sellable'",
          },
          { status: 422 },
        ),
      ),
    )

    renderRoute('/stores/STORE-DN1', staticClient())
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Bộ lọc không hợp lệ')
    expect(alert).not.toHaveTextContent('Input should be')
  })
})
