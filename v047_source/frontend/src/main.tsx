import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'
import App from './App'
import { SessionUiStoreProvider } from './components/SessionUiStore'
import UiReadyReporter from './components/UiReadyReporter'
import './styles/global.css'
import './styles/v041.css'
import './styles/v049.css'
import './styles/v0410.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 1500 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <UiReadyReporter />
        <SessionUiStoreProvider>
          <App />
        </SessionUiStoreProvider>
        <Toaster richColors position="bottom-right" />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
