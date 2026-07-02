import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import ScrollToTop from './ScrollToTop'
import { ToastProvider } from './toast'
import { initTelemetry } from './telemetry'
import { uuidFallback } from './utils/uuid'

// Polyfill crypto.randomUUID for non-secure contexts (HTTP + public IP).
// Must use uuidFallback (getRandomValues-based) — using uuid() would
// recurse because uuid() delegates to crypto.randomUUID when available,
// which is now this polyfill.
if (typeof window !== 'undefined' && window.crypto && !window.crypto.randomUUID) {
  ;(window.crypto as any).randomUUID = uuidFallback
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
