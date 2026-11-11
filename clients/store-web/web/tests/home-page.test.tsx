import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { SHOP_SEARCH_ITEMS, STORE_SUGGESTION } from '../src/test/fixtures'
import { server } from '../src/test/server'
import { renderRoute } from './testUtils'

describe('HomePage (customer shop)', () => {
  it('shows the hero search and the product grid', async () => {
    renderRoute('/')
    expect(
      screen.getByRole('heading', { level: 1, name: 'Tìm hàng hoá gần bạn nhất' }),
    ).toBeInTheDocument()
    expect(await screen.findByText('Fresh milk 1L')).toBeInTheDocument()
    expect(screen.getByText('Butter cookies 200g')).toBeInTheDocument()
  })

  it('points each product at the nearest store that has stock', async () => {
    renderRoute('/')
    const heading = await screen.findByText('Fresh milk 1L')
    const card = heading.closest('.product-card')!
    expect(card).toHaveTextContent('GỢI Ý CỬA HÀNG GẦN NHẤT')
    expect(card).toHaveTextContent('Cửa hàng Hải Châu')
    expect(card).toHaveTextContent('Còn 40 sản phẩm')
    // 0.2 km is a real road distance, so it is shown as kilometres with no label.
    expect(card).toHaveTextContent('0,2 km')
    expect(card).not.toHaveTextContent('đường chim bay')
  })

  it('shows the street address of the suggested store', async () => {
    renderRoute('/')
    const card = (await screen.findByText('Fresh milk 1L')).closest('.product-card')!
    expect(card).toHaveTextContent('123 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, Đà Nẵng')
  })

  it('marks a straight-line distance instead of passing it off as a road one', async () => {
    server.use(
      http.get('/api/shop/search', () =>
        HttpResponse.json({
          q: ' ',
          latitude: 16.0678,
          longitude: 108.2208,
          total: 1,
          items: [
            {
              ...SHOP_SEARCH_ITEMS[0],
              stores: [{ ...STORE_SUGGESTION, distance_km: 1.7, distance_kind: 'straight' }],
              nearest: { ...STORE_SUGGESTION, distance_km: 1.7, distance_kind: 'straight' },
            },
          ],
        }),
      ),
    )

    renderRoute('/')
    const card = (await screen.findByText('Fresh milk 1L')).closest('.product-card')!
    expect(card).toHaveTextContent('1,7 km (đường chim bay)')
  })

  it('says plainly when no nearby store has the product', async () => {
    renderRoute('/')
    const card = (await screen.findByText('Butter cookies 200g')).closest('.product-card')!
    expect(card).toHaveTextContent('Tạm hết hàng ở tất cả các cửa hàng lân cận')
  })

  it('links a suggestion to the store product page', async () => {
    renderRoute('/')
    const link = await screen.findByRole('link', { name: /Xem kho hàng/ })
    expect(link).toHaveAttribute('href', '/stores/STORE-DN1/products/SKU-0001')
  })

  it('filters by a search term', async () => {
    const user = userEvent.setup()
    renderRoute('/')
    await screen.findByText('Fresh milk 1L')

    await user.type(screen.getByPlaceholderText(/Bạn đang tìm gì/), 'cookies')
    expect(await screen.findByText('Butter cookies 200g')).toBeInTheDocument()
    expect(screen.queryByText('Fresh milk 1L')).not.toBeInTheDocument()
  })

  it('shows the current shopping location in the header', async () => {
    renderRoute('/')
    const locationBar = screen.getByTitle('Thay đổi vị trí của bạn')
    expect(locationBar).toHaveTextContent('Trung tâm Hải Châu, Đà Nẵng')
  })
})
