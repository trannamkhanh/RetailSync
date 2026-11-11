import { useState } from 'react'
import { useAuth, useMyAddresses, useSampleAddresses, useSaveAddress } from '../api/queries'
import type { AddressItem } from '../api/types'
import { useUserLocation } from '../lib/locationContext'

interface AddressModalProps {
  isOpen: boolean
  onClose: () => void
}

export function AddressModal({ isOpen, onClose }: AddressModalProps) {
  const { location, setLocation, detectCurrentLocation, isDetecting, errorMsg } = useUserLocation()
  const auth = useAuth()
  const isLoggedIn = Boolean(auth.data?.customer)

  const sample = useSampleAddresses()
  const mine = useMyAddresses(isLoggedIn)
  const saveAddr = useSaveAddress()

  const [isAdding, setIsAdding] = useState(false)
  const [label, setLabel] = useState('')
  const [addressText, setAddressText] = useState('')

  if (!isOpen) return null

  function handleSelect(addr: AddressItem) {
    setLocation(addr)
    onClose()
  }

  async function handleAutoDetect() {
    const success = await detectCurrentLocation()
    if (success) {
      onClose()
    }
  }

  async function handleSaveNew(e: React.FormEvent) {
    e.preventDefault()
    if (!label.trim() || !addressText.trim()) return

    // For new custom address without custom geocoding service, use current coords as center:
    saveAddr.mutate(
      {
        label: label.trim(),
        address_text: addressText.trim(),
        latitude: location.latitude,
        longitude: location.longitude,
      },
      {
        onSuccess: (saved) => {
          setLocation(saved)
          setIsAdding(false)
          setLabel('')
          setAddressText('')
          onClose()
        },
      },
    )
  }

  return (
    <div className="modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">Chọn vị trí giao / mua hàng</h2>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            ✕
          </button>
        </div>

        <p style={{ color: 'var(--note)', fontSize: 13, marginTop: 0 }}>
          Hệ thống sẽ gợi ý cửa hàng gần bạn nhất còn sẵn hàng để bạn ghé mua hoặc nhận hàng nhanh
          nhất.
        </p>

        <div style={{ marginBottom: 16 }}>
          <button
            type="button"
            className="btn btn-primary"
            style={{ width: '100%' }}
            onClick={handleAutoDetect}
            disabled={isDetecting}
          >
            {isDetecting ? 'Đang định vị…' : '📍 Dùng vị trí hiện tại (GPS)'}
          </button>
          {errorMsg && (
            <p style={{ color: 'var(--danger)', fontSize: 12, marginTop: 6 }}>{errorMsg}</p>
          )}
        </div>

        {/* Saved Addresses (if logged in) */}
        {isLoggedIn && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, margin: '12px 0 8px' }}>Địa chỉ của tôi</h3>
              {!isAdding && (
                <button
                  type="button"
                  className="btn btn-sm btn-outline"
                  onClick={() => setIsAdding(true)}
                >
                  + Thêm mới
                </button>
              )}
            </div>

            {isAdding && (
              <form
                onSubmit={handleSaveNew}
                style={{
                  background: 'var(--soft)',
                  padding: 12,
                  borderRadius: 'var(--radius-md)',
                  marginBottom: 12,
                }}
              >
                <div className="form-group" style={{ marginBottom: 8 }}>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Tên gợi nhớ (Vd: Nhà riêng, Công ty)"
                    value={label}
                    onChange={(e) => setLabel(e.target.value)}
                    required
                  />
                </div>
                <div className="form-group" style={{ marginBottom: 8 }}>
                  <input
                    type="text"
                    className="form-input"
                    placeholder="Địa chỉ chi tiết (Đường, Phường, Quận...)"
                    value={addressText}
                    onChange={(e) => setAddressText(e.target.value)}
                    required
                  />
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="submit" className="btn btn-sm btn-primary" disabled={saveAddr.isPending}>
                    Lưu địa chỉ
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

            {mine.data?.addresses.map((addr) => {
              const selected = location.address_id === addr.address_id
              return (
                <div
                  key={addr.address_id}
                  className={`address-item ${selected ? 'selected' : ''}`}
                  onClick={() => handleSelect(addr)}
                >
                  <div>
                    <div style={{ fontWeight: 700 }}>{addr.label}</div>
                    <div style={{ fontSize: 12, color: 'var(--note)' }}>{addr.address_text}</div>
                  </div>
                  {selected && <span style={{ color: 'var(--primary)', fontWeight: 800 }}>✓</span>}
                </div>
              )
            })}
          </div>
        )}

        {/* Sample Addresses */}
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 700, margin: '12px 0 8px' }}>
            Địa điểm gợi ý tại Đà Nẵng
          </h3>
          {sample.data?.addresses.map((addr) => {
            const selected = location.address_id === addr.address_id
            return (
              <div
                key={addr.address_id}
                className={`address-item ${selected ? 'selected' : ''}`}
                onClick={() => handleSelect(addr)}
              >
                <div>
                  <div style={{ fontWeight: 700 }}>{addr.label}</div>
                  <div style={{ fontSize: 12, color: 'var(--note)' }}>{addr.address_text}</div>
                </div>
                {selected && <span style={{ color: 'var(--primary)', fontWeight: 800 }}>✓</span>}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
