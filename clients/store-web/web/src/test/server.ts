import { setupServer } from 'msw/node'

/** No default handlers: each test registers the responses it needs. */
export const server = setupServer()
