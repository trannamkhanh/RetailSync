import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useRegister } from '../api/queries'
import { Layout } from '../components/Layout'

export function RegisterPage() {
  const navigate = useNavigate()
  const register = useRegister()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setErrorMsg(null)
    if (password.length < 8) {
      setErrorMsg('Mật khẩu phải có ít nhất 8 ký tự.')
      return
    }

    register.mutate(
      { email, full_name: fullName, password },
      {
        onSuccess: () => {
          navigate('/')
        },
        onError: (err: any) => {
          setErrorMsg(err.message || 'Đăng ký không thành công.')
        },
      },
    )
  }

  return (
    <Layout>
      <div className="container">
        <div className="auth-box">
          <h1 style={{ fontSize: 24, fontWeight: 800, margin: '0 0 8px', textAlign: 'center' }}>
            Tạo tài khoản
          </h1>
          <p style={{ textAlign: 'center', color: 'var(--note)', fontSize: 13, marginBottom: 24 }}>
            Đăng ký để trải nghiệm mua sắm nhanh chóng cùng RetailSync
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
              <label className="form-label" htmlFor="register-name">
                Họ và tên
              </label>
              <input
                id="register-name"
                type="text"
                className="form-input"
                placeholder="Nguyễn Văn A"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="register-email">
                Email
              </label>
              <input
                id="register-email"
                type="email"
                className="form-input"
                placeholder="tenban@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="register-password">
                Mật khẩu (ít nhất 8 ký tự)
              </label>
              <input
                id="register-password"
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
              disabled={register.isPending}
            >
              {register.isPending ? 'Đang tạo tài khoản…' : 'Đăng ký'}
            </button>
          </form>

          <div style={{ textAlign: 'center', marginTop: 20, fontSize: 13, color: 'var(--note)' }}>
            Đã có tài khoản?{' '}
            <Link to="/login" style={{ color: 'var(--primary)', fontWeight: 700 }}>
              Đăng nhập
            </Link>
          </div>
        </div>
      </div>
    </Layout>
  )
}
