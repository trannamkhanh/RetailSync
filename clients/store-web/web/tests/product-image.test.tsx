import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { renderRoute } from './testUtils'

describe('ProductImage', () => {
  it('shows the photo on the shop card', async () => {
    renderRoute('/')
    const heading = await screen.findByText('Fresh milk 1L')
    const card = heading.closest('.product-card')!
    const img = card.querySelector('img')
    expect(img).not.toBeNull()
    expect(img).toHaveAttribute('src', '/products/fresh-milk.jpg')
    // The picture is decorative next to the visible name, but alt text still
    // names the product for a screen reader.
    expect(img).toHaveAttribute('alt', 'Fresh milk 1L')
  })

  it('shows a thumbnail in the store table', async () => {
    renderRoute('/stores/STORE-DN1')
    const row = (await screen.findByText('Fresh milk 1L')).closest('tr')!
    expect(row.querySelector('img.product-image--thumb')).not.toBeNull()
  })

  it('shows the photo on the product detail page', async () => {
    renderRoute('/stores/STORE-DN1/products/SKU-0001')
    const card = await screen.findByLabelText('Thông tin sản phẩm')
    expect(card.querySelector('img.product-image--card')).not.toBeNull()
  })
})
