import { QueryClient } from '@tanstack/react-query'

import { ApiError } from './client'

/** Shared defaults: cache briefly, retry transport/5xx once, never retry a 4xx. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500),
      },
    },
  })
}
