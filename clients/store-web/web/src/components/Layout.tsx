import { useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth, useLogout } from '../api/queries'
import { useUserLocation } from '../lib/locationContext'
import { AddressModal } from './AddressModal'

interface Breadcrumb {
  label: string
  to?: string
}

interface LayoutProps {
  title?: string
  breadcrumbs?: Breadcrumb[]
  actions?: ReactNode
  children: ReactNode
}

export function Layout({ title, breadcrumbs, actions, children }: LayoutProps) {
  const { location } = useUserLocation()
  const { pathname } = useLocation()
  const auth = useAuth()
  const logout = useLogout()
  const [modalOpen, setModalOpen] = useState(false)

  const customer = auth.data?.customer

  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <Link to="/" className="brand-group">
            <div className="brand-logo">RS</div>
            <div>
              <div className="brand-name">RetailSync</div>
            </div>
            <span className="brand-badge">Shop</span>
          </Link>

          <div className="header-center">
            <button
              type="button"
              className="location-bar"
              onClick={() => setModalOpen(true)}
              title="Thay đổi vị trí của bạn"
            >
              <span className="location-icon">📍</span>
              <span className="location-text">
                Gần: <strong>{location.label}</strong>
              </span>
              <span style={{ fontSize: 11, color: 'var(--note)', marginLeft: 4 }}>▼</span>
            </button>
          </div>

          <nav className="header-actions">
            <Link to="/" className={`nav-link ${pathname === '/' ? 'active' : ''}`}>
              Khám phá
            </Link>
            <Link
              to="/stores"
              className={`nav-link ${pathname.startsWith('/stores') ? 'active' : ''}`}
              title="Tra cứu danh mục chi tiết theo từng chi nhánh"
            >
              Chi nhánh
            </Link>

            {customer ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Link to="/account" className="nav-link" style={{ fontWeight: 700 }}>
                  👤 {customer.full_name}
                </Link>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => logout.mutate()}
                  disabled={logout.isPending}
                >
                  Đăng xuất
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 8 }}>
                <Link to="/login" className="btn btn-sm btn-outline">
                  Đăng nhập
                </Link>
                <Link to="/register" className="btn btn-sm btn-primary">
                  Đăng ký
                </Link>
              </div>
            )}
          </nav>
        </div>
      </header>

      {/* Internal Sub-header for stores breadcrumb and title if provided */}
      {title && (
        <div style={{ background: '#fff', borderBottom: '1px solid var(--line)', padding: '16px 20px' }}>
          <div style={{ maxWidth: 1200, margin: '0 auto' }}>
            {breadcrumbs && breadcrumbs.length > 0 && (
              <nav className="breadcrumb" aria-label="Đường dẫn" style={{ marginBottom: 6, fontSize: 13, color: 'var(--note)' }}>
                {breadcrumbs.map((crumb) =>
                  crumb.to ? (
                    <span key={crumb.label}>
                      <Link to={crumb.to}>{crumb.label}</Link>
                    </span>
                  ) : (
                    <span key={crumb.label} aria-current="page">
                      {crumb.label}
                    </span>
                  ),
                )}
              </nav>
            )}
            <h1 style={{ fontSize: 22, fontWeight: 800, margin: '0 0 4px' }}>{title}</h1>
            {actions}
          </div>
        </div>
      )}

      <main>{children}</main>

      <AddressModal isOpen={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  )
}
