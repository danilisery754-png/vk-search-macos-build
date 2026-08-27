import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ResultsPage from './ResultsPage'

const runs = {
  current_run_id: 2,
  items: [
    { id: 2, state: 'completed', started_at: '2026-08-25T12:00:00', finished_at: '2026-08-25T12:10:00', original_count: 100, processed_count: 100, success_count: 80, failure_count: 20 },
    { id: 1, state: 'completed', started_at: '2026-08-24T12:00:00', finished_at: '2026-08-24T12:20:00', original_count: 50, processed_count: 50, success_count: 30, failure_count: 20 },
  ],
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage(kind: 'success' | 'failed') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><ResultsPage kind={kind} /></QueryClientProvider>)
}

afterEach(() => {
  sessionStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ResultsPage run isolation', () => {
  it('persists the selected archived run across success and failed screens', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request); calls.push(url)
      if (url.endsWith('/api/runs')) return json(runs)
      if (url.includes('/api/results/')) return json({ total: 0, items: [] })
      throw new Error(`Unexpected request ${url}`)
    }))
    const first = renderPage('success')
    await waitFor(() => expect(calls.some(call => call.includes('/api/results/success?run_id=2'))).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: /Запуски/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /Запуск #1/ }))
    await waitFor(() => expect(calls.some(call => call.includes('/api/results/success?run_id=1'))).toBe(true))
    first.unmount()

    renderPage('failed')
    await waitFor(() => expect(calls.some(call => call.includes('/api/results/failed?run_id=1'))).toBe(true))
    fireEvent.click(await screen.findByRole('button', { name: 'Вернуться к текущему запуску' }))
    await waitFor(() => expect(calls.some(call => call.includes('/api/results/failed?run_id=2'))).toBe(true))
  })

  it('sends the selected run id with exports', async () => {
    const fetchMock = vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request)
      if (url.endsWith('/api/runs')) return json(runs)
      if (url.includes('/api/results/success?')) return json({ total: 0, items: [] })
      if (url.endsWith('/api/results/success/export') && init?.method === 'POST') return new Response(new Blob(['ok']), { status: 200, headers: { 'Content-Disposition': "attachment; filename*=UTF-8''results.txt" } })
      throw new Error(`Unexpected request ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    const createObjectURL = vi.fn(() => 'blob:test')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    renderPage('success')
    const runTrigger = await screen.findByRole('button', { name: /Запуски · #2/ })
    fireEvent.click(runTrigger)
    fireEvent.click(screen.getByRole('menuitem', { name: /Запуск #1/ }))
    fireEvent.click(screen.getByRole('button', { name: 'TXT' }))
    await waitFor(() => {
      const exportCall = fetchMock.mock.calls.find(call => String(call[0]).endsWith('/api/results/success/export'))
      expect(exportCall).toBeTruthy()
      expect(JSON.parse(String(exportCall?.[1]?.body))).toMatchObject({ run_id: 1, mode: 'links' })
    })
  })
})
