import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderRoute } from './testUtils'

describe('ProductPage', () => {
  it('labels an expired batch and strikes it through', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0004')
    const row = (await screen.findByText('B-STORE-DN1-SKU-0004-0')).closest('tr')!
    expect(row).toHaveTextContent('hết hạn')
    expect(row).toHaveClass('expired')
  })

  it('does not count the expired batch as sellable', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0004')
    const sellable = (await screen.findByText('Còn bán')).nextElementSibling!
    expect(sellable).toHaveTextContent('25')
    expect(sellable).not.toHaveTextContent('40')
  })

  it('treats a batch expiring today as sellable', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0004')
    const row = (await screen.findByText('B-STORE-DN1-SKU-0004-1')).closest('tr')!
    expect(row).toHaveTextContent('còn bán')
    expect(row).not.toHaveClass('expired')
  })

  it('formats the price from the string value', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0001')
    expect(await screen.findByText('32.000 ₫')).toBeInTheDocument()
  })

  it('shows the total stock separately from the sellable quantity', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0004')
    const total = (await screen.findByText('Tổng tồn')).nextElementSibling!
    expect(total).toHaveTextContent('40')
    expect(total).toHaveTextContent('15 đơn vị hết hạn')
  })

  it('links back to the store', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0001')
    const back = await screen.findByRole('link', { name: /Về Cửa hàng Hải Châu/ })
    expect(back).toHaveAttribute('href', '/stores/STORE-DN1')
  })

  it('explains a missing product instead of rendering a blank page', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-NOPE')
    expect(await screen.findByText('Không tìm thấy sản phẩm')).toBeInTheDocument()
  })
})
