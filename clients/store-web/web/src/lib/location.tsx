import { useState, type ReactNode } from 'react'

import type { AddressItem } from '../api/types'
import { LocationContext } from './locationContext'
import { DEFAULT_LOCATION, STORAGE_KEY } from './locationDefaults'

function readStoredLocation(): AddressItem {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored) as AddressItem
  } catch {
    // A corrupt or blocked storage falls back to the default location.
  }
  return DEFAULT_LOCATION
}

export function LocationProvider({ children }: { children: ReactNode }) {
  const [location, setLocationState] = useState<AddressItem>(readStoredLocation)
  const [isDetecting, setIsDetecting] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  function setLocation(loc: AddressItem) {
    setLocationState(loc)
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(loc))
    } catch {
      // Storage being unavailable must not break choosing an address.
    }
  }

  async function detectCurrentLocation(): Promise<boolean> {
    if (!navigator.geolocation) {
      setErrorMsg('Trình duyệt không hỗ trợ định vị.')
      return false
    }

    setIsDetecting(true)
    setErrorMsg(null)

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          setIsDetecting(false)
          setLocation({
            address_id: 'GEO-CURRENT',
            label: 'Vị trí hiện tại của bạn',
            address_text: `Toạ độ: ${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`,
            latitude: pos.coords.latitude,
            longitude: pos.coords.longitude,
          })
          resolve(true)
        },
        (err) => {
          setIsDetecting(false)
          setErrorMsg(
            err.code === err.PERMISSION_DENIED
              ? 'Bạn đã từ chối chia sẻ vị trí. Hãy chọn địa chỉ có sẵn.'
              : 'Không thể xác định vị trí.',
          )
          resolve(false)
        },
        { timeout: 10000, enableHighAccuracy: true },
      )
    })
  }

  return (
    <LocationContext.Provider
      value={{ location, setLocation, detectCurrentLocation, isDetecting, errorMsg }}
    >
      {children}
    </LocationContext.Provider>
  )
}
