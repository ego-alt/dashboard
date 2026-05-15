import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'

const API_TARGET = 'http://localhost:8000'

// Backend paths the SPA calls same-origin. Proxied in dev so `npm run dev`
// behaves like production (served behind nginx) without needing CORS.
// `/login` + `/logout` are also client routes — the bypass returns the SPA
// shell for browser navigations (Accept: text/html) and only proxies
// XHR/fetch (Accept: */*) through to the backend.
const API_PATHS = ['/login', '/logout', '/me', '/auth', '/ping', '/containers', '/stats']

function apiProxy() {
  const proxy = {}
  for (const path of API_PATHS) {
    proxy[path] = {
      target: API_TARGET,
      changeOrigin: true,
      bypass(req) {
        const accept = req.headers.accept || ''
        if (req.method === 'GET' && accept.includes('text/html')) {
          return '/index.html'
        }
      },
    }
  }
  return proxy
}

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: { proxy: apiProxy() },
})
