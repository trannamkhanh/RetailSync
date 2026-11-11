import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev: Vite on 5173 proxies /api to the API on 5180, so no CORS is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5180', changeOrigin: false },
    },
  },
})
