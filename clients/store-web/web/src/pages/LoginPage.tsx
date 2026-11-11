import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useLogin } from '../api/queries'
import { Layout } from '../components/Layout'

export function LoginPage() {
  const navigate = useNavigate()
  const login = useLogin()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    login.mutate(
      { email, password },
      {
        onSuccess: () => {
          navigate('/')
        },
        onError: (err: any) => {
          setErrorMsg(err.message || 'Đăng nhập không thành công.')
        },
      },
    )
  }

  return (
    <Layout>
      <div className="container">
        <div className="auth-box">
          <h1 style={{ fontSize: 24, fontWeight: 800, margin: '0 0 8px', textAlign: 'center' }}>
            Đăng nhập
          </h1>
          <p style={{ textAlign: 'center', color: 'var(--note)', fontSize: 13, marginBottom: 24 }}>
            Đăng nhập để lưu địa chỉ và nhận gợi ý chuẩn xác nhất
          </p>

          {errorMsg && (
            <div
              style={{
                background: 'var(--danger-light)',
                color: 'var(--danger)',
                padding: '10px 14px',
                borderRadius: 'var(--radius-md)',
                fontSize: 13,
                marginBottom: 16,
              }}
            >
              {errorMsg}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label" htmlFor="login-email">
                Email
              </label>
              <input
                id="login-email"
                type="email"
                className="form-input"
                placeholder="tenban@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="login-password">
                Mật khẩu
              </label>
              <input
                id="login-password"
                type="password"
                className="form-input"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            <button
              type="submit"
              className="btn btn-primary"
              style={{ width: '100%', marginTop: 8 }}
              disabled={login.isPending}
            >
              {login.isPending ? 'Đang xử lý…' : 'Đăng nhập'}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: 20, fontSize: 13, color: 'var(--note)' }}>
            Chưa có tài khoản?{' '}
            <Link to="/register" style={{ color: 'var(--primary)', fontWeight: 700 }}>
              Đăng ký ngay
            </Link>
          </div>
        </div>
      </div>
    </Layout>
  )
}
