import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import ScrollToTop from './ScrollToTop'
import { ToastProvider } from './toast'
import { initTelemetry } from './telemetry'
import { uuid } from './utils/uuid'

// Polyfill crypto.randomUUID for non-secure contexts (HTTP + public IP).
// Without this, third-party libs that reach for crypto.randomUUID crash.
if (typeof window !== 'undefined' && window.crypto && !window.crypto.randomUUID) {
  ;(window.crypto as any).randomUUID = () => uuid()
}

// Init PostHog before the first render so page-view auto-capture starts on route zero.
initTelemetry()

// AuthProvider is inside App — no need to import here.

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      staleTime: 5_000,
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <BrowserRouter>
          <ScrollToTop />
          <App />
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
