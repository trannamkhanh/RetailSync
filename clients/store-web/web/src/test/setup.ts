import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { handlers } from './handlers'
import { server } from './server'

beforeAll(() => {
  server.listen({ onUnhandledFrame: 'error' })
  server.use(...handlers)
})
afterEach(() => {
  cleanup()
  server.resetHandlers(...handlers)
})
afterAll(() => server.close())
