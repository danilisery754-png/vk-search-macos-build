import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  client.setQueryData(['settings-shell'], { ui_scale: 1 })
  render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>)
  return client
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('SettingsPage v0.4.9 scale', () => {
  it('keeps slider changes as a draft until explicit Save and updates Shell only after success', async () => {
    const calls: Array<{ url: string; method: string; body?: string }> = []
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'
      calls.push({ url, method, body: typeof init?.body === 'string' ? init.body : undefined })
      if (url.endsWith('/api/settings') && method === 'GET') return json({ ui_scale: 1, inbox_sync_seconds: 30 })
      if (url.endsWith('/api/backups') && method === 'GET') return json([])
      if (url.endsWith('/api/settings') && method === 'PATCH') return json({ ui_scale: 2, inbox_sync_seconds: 30 })
      throw new Error(`Unexpected request: ${method} ${url}`)
    }))

    const client = renderPage()
    fireEvent.click(await screen.findByRole('tab', { name: 'Дополнительно' }))
    const slider = screen.getByRole('slider', { name: /Масштаб интерфейса/ })
    fireEvent.change(slider, { target: { value: '200' } })

    expect(screen.getByText(/Масштаб интерфейса: 200%/)).toBeInTheDocument()
    expect(calls.filter(call => call.method === 'PATCH')).toHaveLength(0)
    expect(client.getQueryData(['settings-shell'])).toEqual({ ui_scale: 1 })

    fireEvent.click(screen.getByRole('button', { name: /^Сохранить$/ }))
    await waitFor(() => expect(calls.filter(call => call.method === 'PATCH')).toHaveLength(1))
    const patch = calls.find(call => call.method === 'PATCH')
    expect(JSON.parse(patch?.body || '{}')).toEqual({ values: { ui_scale: 2 } })
    await waitFor(() => expect(client.getQueryData(['settings-shell'])).toMatchObject({ ui_scale: 2 }))
  })

  it('loads the persisted scale into the draft after restart/query load', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request)
      if (url.endsWith('/api/settings')) return json({ ui_scale: 2.5 })
      if (url.endsWith('/api/backups')) return json([])
      throw new Error(`Unexpected request: ${url}`)
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('tab', { name: 'Дополнительно' }))
    expect(screen.getByRole('slider', { name: /Масштаб интерфейса/ })).toHaveValue('250')
  })
})
