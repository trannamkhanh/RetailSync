import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { renderRoute } from './testUtils'

describe('StorePage', () => {
  it('renders the seeded catalog', async () => {
    renderRoute('/stores/STORE-DN1')
    expect(await screen.findByText('Fresh milk 1L')).toBeInTheDocument()
    expect(screen.getByText('Bread 400g')).toBeInTheDocument()
    expect(screen.getByText(/9 sản phẩm trong hệ thống/)).toBeInTheDocument()
  })

  it('says where to buy a product this branch does not stock', async () => {
    renderRoute('/stores/STORE-DN1')
    const row = (await screen.findByText('Rice 50kg')).closest('tr')!
    expect(row).toHaveTextContent('Cửa hàng Thanh Khê')
    expect(row).toHaveTextContent('4,9 km')
  })

  it('marks a product stocked by the branch being viewed as available here', async () => {
    renderRoute('/stores/STORE-DN1')
    const row = (await screen.findByText('Fresh milk 1L')).closest('tr')!
    expect(row).toHaveTextContent('tại đây')
  })

  it('shows the sellable quantity, never the inventory quantity', async () => {
    renderRoute('/stores/STORE-DN1')
    const row = (await screen.findByText('Bread 400g')).closest('tr')!
    const cells = within(row).getAllByRole('cell')
    expect(cells[4]).toHaveTextContent('25')
    expect(cells[4]).not.toHaveTextContent('40')
  })

  it('formats money from the string price', async () => {
    renderRoute('/stores/STORE-DN1')
    expect(await screen.findByText('32.000 ₫')).toBeInTheDocument()
  })

  it('marks a product with nothing sellable as out of stock', async () => {
    renderRoute('/stores/STORE-DN1')
    const row = (await screen.findByText('Butter cookies 200g')).closest('tr')!
    expect(row).toHaveTextContent('hết hàng')
  })

  it('applies a category filter without a full reload', async () => {
    const user = userEvent.setup()
    renderRoute('/stores/STORE-DN1')
    await screen.findByText('Fresh milk 1L')

    await user.selectOptions(screen.getByLabelText('Danh mục'), 'Dairy')
    expect(screen.getByText('Yogurt 100g')).toBeInTheDocument()
  })

  it('resets the offset when a filter changes', async () => {
    const user = userEvent.setup()
    renderRoute('/stores/STORE-DN1?offset=5')
    await screen.findByText('Fresh milk 1L')

    await user.click(screen.getByLabelText('Chỉ còn hàng'))
    expect(screen.queryByText(/6–/)).not.toBeInTheDocument()
  })
})
