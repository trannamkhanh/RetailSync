import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'

import { createQueryClient } from './api/queryClient'
import { LocationProvider } from './lib/location'
import { AccountPage } from './pages/AccountPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { ProductPage } from './pages/ProductPage'
import { RegisterPage } from './pages/RegisterPage'
import { StorePage } from './pages/StorePage'
import { StoresPage } from './pages/StoresPage'

const queryClient = createQueryClient()

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <LocationProvider>
        <BrowserRouter>
          <Routes>
            {/* Customer Shop routes */}
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/account" element={<AccountPage />} />

            {/* Store Inspection & Inventory routes */}
            <Route path="/stores" element={<StoresPage />} />
            <Route path="/stores/:storeId" element={<StorePage />} />
            <Route path="/stores/:storeId/products/:sku" element={<ProductPage />} />

            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </BrowserRouter>
      </LocationProvider>
    </QueryClientProvider>
  )
}
