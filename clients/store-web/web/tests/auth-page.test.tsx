import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { renderRoute } from './testUtils'

describe('LoginPage', () => {
  it('logs in and returns to the shop', async () => {
    const user = userEvent.setup()
    renderRoute('/login')

    await user.type(screen.getByLabelText('Email'), 'a@b.test')
    await user.type(screen.getByLabelText('Mật khẩu'), 'matkhau123')
    await user.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    // The shared handler signs in as "Khách Test" and the header shows the name.
    expect(await screen.findByText(/Khách Test/)).toBeInTheDocument()
  })

  it('links to registration', () => {
    renderRoute('/login')
    expect(screen.getByRole('link', { name: 'Đăng ký ngay' })).toHaveAttribute('href', '/register')
  })
})

describe('RegisterPage', () => {
  it('rejects a password shorter than 8 characters before calling the API', async () => {
    const user = userEvent.setup()
    renderRoute('/register')

    await user.type(screen.getByLabelText('Họ và tên'), 'Người Dùng')
    await user.type(screen.getByLabelText('Email'), 'moi@b.test')
    await user.type(screen.getByLabelText(/Mật khẩu/), 'ngan')
    await user.click(screen.getByRole('button', { name: 'Đăng ký' }))

    expect(await screen.findByText('Mật khẩu phải có ít nhất 8 ký tự.')).toBeInTheDocument()
  })

  it('registers and signs the customer in', async () => {
    const user = userEvent.setup()
    renderRoute('/register')

    await user.type(screen.getByLabelText('Họ và tên'), 'Người Dùng')
    await user.type(screen.getByLabelText('Email'), 'moi@b.test')
    await user.type(screen.getByLabelText(/Mật khẩu/), 'matkhau123')
    await user.click(screen.getByRole('button', { name: 'Đăng ký' }))

    expect(await screen.findByText(/Khách Mới/)).toBeInTheDocument()
  })
})
