import { createContext, useContext } from 'react'

import type { AddressItem } from '../api/types'

export interface LocationContextType {
  location: AddressItem
  setLocation: (loc: AddressItem) => void
  detectCurrentLocation: () => Promise<boolean>
  isDetecting: boolean
  errorMsg: string | null
}

export const LocationContext = createContext<LocationContextType | null>(null)

export function useUserLocation(): LocationContextType {
  const ctx = useContext(LocationContext)
  if (!ctx) throw new Error('useUserLocation must be used within LocationProvider')
  return ctx
}
