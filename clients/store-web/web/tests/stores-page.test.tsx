import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderRoute } from './testUtils'

describe('StoresPage', () => {
  it('renders the three seeded stores with their counts', async () => {
    renderRoute('/stores')
    expect(await screen.findByText('Cửa hàng Hải Châu')).toBeInTheDocument()
    expect(screen.getByText('Cửa hàng Thanh Khê')).toBeInTheDocument()
    expect(screen.getByText('Cửa hàng Sơn Trà')).toBeInTheDocument()
    expect(screen.getAllByText('9 SKU')).toHaveLength(3)
    expect(screen.getByText('360 đơn vị')).toBeInTheDocument()
    expect(screen.getByText('225 đơn vị')).toBeInTheDocument()
  })

  it('links every card to its store route', async () => {
    renderRoute('/stores')
    const link = await screen.findByRole('link', { name: /Hải Châu/ })
    expect(link).toHaveAttribute('href', '/stores/STORE-DN1')
  })

  it('shows the street address on each store card', async () => {
    renderRoute('/stores')
    expect(
      await screen.findByText('123 Bạch Đằng, Phường Hải Châu 1, Quận Hải Châu, Đà Nẵng'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('456 Nguyễn Văn Linh, Phường Tân Chính, Quận Thanh Khê, Đà Nẵng'),
    ).toBeInTheDocument()
  })

  it('shows a loading message first', () => {
    renderRoute('/stores')
    expect(screen.getByText('Đang tải danh sách cửa hàng…')).toBeInTheDocument()
  })
})
