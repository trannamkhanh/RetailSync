import { QueryClientProvider, type QueryClient } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import { createQueryClient } from '../src/api/queryClient'
import { LocationProvider } from '../src/lib/location'
import { AccountPage } from '../src/pages/AccountPage'
import { HomePage } from '../src/pages/HomePage'
import { LoginPage } from '../src/pages/LoginPage'
import { ProductPage } from '../src/pages/ProductPage'
import { RegisterPage } from '../src/pages/RegisterPage'
import { StorePage } from '../src/pages/StorePage'
import { StoresPage } from '../src/pages/StoresPage'

/** Render one route with the same providers the real app installs. */
export function renderRoute(path: string, client: QueryClient = createQueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <LocationProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/account" element={<AccountPage />} />
            <Route path="/stores" element={<StoresPage />} />
            <Route path="/stores/:storeId" element={<StorePage />} />
            <Route path="/stores/:storeId/products/:sku" element={<ProductPage />} />
          </Routes>
        </MemoryRouter>
      </LocationProvider>
    </QueryClientProvider>,
  )
}
