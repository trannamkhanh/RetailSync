import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth, useDeleteAddress, useLogout, useMyAddresses, useSaveAddress } from '../api/queries'
import { Layout } from '../components/Layout'
import { StateBlock } from '../components/StateBlock'
import { useUserLocation } from '../lib/locationContext'

export function AccountPage() {
  const auth = useAuth()
  const logout = useLogout()
  const { location, setLocation } = useUserLocation()

  const customer = auth.data?.customer
  const addresses = useMyAddresses(Boolean(customer))
  const saveAddr = useSaveAddress()
  const deleteAddr = useDeleteAddress()

  const [isAdding, setIsAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [addressText, setAddressText] = useState('')

  if (auth.isPending) {
    return (
      <Layout>
        <div className="container">
          <StateBlock kind="loading" title="Đang tải thông tin tài khoản…" />
        </div>
      </Layout>
    )
  }

  if (!customer) {
    return (
      <Layout>
        <div className="container">
          <div className="auth-box" style={{ textAlign: 'center' }}>
            <h2 style={{ fontSize: 20, fontWeight: 800 }}>Bạn chưa đăng nhập</h2>
            <p style={{ color: 'var(--note)', marginBottom: 20 }}>
              Vui lòng đăng nhập để xem thông tin và quản lý sổ địa chỉ của bạn.
            </p>
            <Link to="/login" className="btn btn-primary" style={{ width: '100%' }}>
              Đăng nhập ngay
            </Link>
          </div>
        </div>
      </Layout>
    )
  }

  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!label.trim() || !addressText.trim()) return

    saveAddr.mutate(
      {
        label: label.trim(),
        address_text: addressText.trim(),
        latitude: location.latitude,
        longitude: location.longitude,
      },
      {
        onSuccess: () => {
          setIsAdding(false)
          setLabel('')
          setAddressText('')
        },
      },
    )
  }

  return (
    <Layout>
      <div className="container" style={{ maxWidth: 760 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 800, margin: '0 0 4px' }}>Tài khoản của tôi</h1>
            <p style={{ color: 'var(--note)', margin: 0 }}>Xin chào, {customer.full_name}!</p>
          </div>
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => logout.mutate()}
            disabled={logout.isPending}
          >
            Đăng xuất
          </button>
        </div>

        {/* Profile Card */}
        <div className="product-card" style={{ marginBottom: 24 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 12px' }}>Thông tin cá nhân</h2>
          <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '8px 16px', fontSize: 14 }}>
            <span style={{ color: 'var(--note)' }}>Họ và tên:</span>
            <strong>{customer.full_name}</strong>
            <span style={{ color: 'var(--note)' }}>Email:</span>
            <span>{customer.email}</span>
            <span style={{ color: 'var(--note)' }}>Mã khách hàng:</span>
            <span>#{customer.customer_id}</span>
          </div>
        </div>

        {/* Saved Addresses */}
        <div className="product-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <div>
              <h2 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Sổ địa chỉ đã lưu</h2>
              <p style={{ fontSize: 12, color: 'var(--note)', margin: '4px 0 0' }}>
                Hệ thống dùng các địa chỉ này để tính khoảng cách tới cửa hàng
              </p>
            </div>
            {!isAdding && (
              <button
                type="button"
                className="btn btn-sm btn-primary"
                onClick={() => setIsAdding(true)}
              >
                + Thêm địa chỉ mới
              </button>
            )}
          </div>

          {isAdding && (
            <form
              onSubmit={handleAdd}
              style={{
                background: 'var(--soft)',
                padding: 16,
                borderRadius: 'var(--radius-md)',
                marginBottom: 16,
                border: '1px solid var(--line)',
              }}
            >
              <div className="form-group">
                <label className="form-label">Tên gợi nhớ</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Vd: Nhà riêng, Văn phòng công ty..."
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  required
                />
              </div>
              <div className="form-group">
                <label className="form-label">Địa chỉ cụ thể</label>
                <input
                  type="text"
                  className="form-input"
                  placeholder="Số nhà, đường, phường, quận..."
                  value={addressText}
                  onChange={(e) => setAddressText(e.target.value)}
                  required
                />
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="submit" className="btn btn-sm btn-primary" disabled={saveAddr.isPending}>
                  {saveAddr.isPending ? 'Đang lưu…' : 'Lưu vào sổ địa chỉ'}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setIsAdding(false)}
                >
                  Huỷ
                </button>
              </div>
            </form>
          )}

          {addresses.isPending && <p>Đang tải danh sách địa chỉ…</p>}

          {addresses.isSuccess && addresses.data.addresses.length === 0 && (
            <p style={{ color: 'var(--note)', textAlign: 'center', padding: '20px 0' }}>
              Bạn chưa lưu địa chỉ nào. Hãy bấm "Thêm địa chỉ mới" để lưu vị trí thân quen!
            </p>
          )}

          {addresses.isSuccess && addresses.data.addresses.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {addresses.data.addresses.map((addr) => {
                const isSelected = location.address_id === addr.address_id
                return (
                  <div
                    key={addr.address_id}
                    className="address-item"
                    style={{ margin: 0 }}
                  >
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <strong>{addr.label}</strong>
                        {isSelected && (
                          <span className="badge" style={{ background: 'var(--primary-light)', color: 'var(--primary-hover)' }}>
                            Đang chọn
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: 13, color: 'var(--note)', marginTop: 2 }}>
                        {addr.address_text}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      {!isSelected && (
                        <button
                          type="button"
                          className="btn btn-sm btn-outline"
                          onClick={() => setLocation(addr)}
                        >
                          Chọn vị trí này
                        </button>
                      )}
                      <button
                        type="button"
                        className="btn btn-sm"
                        style={{ color: 'var(--danger)' }}
                        onClick={() => deleteAddr.mutate(addr.address_id)}
                        disabled={deleteAddr.isPending}
                      >
                        Xoá
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </Layout>
  )
}
