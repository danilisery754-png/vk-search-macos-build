import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Shell from './Shell'

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function renderShell(scale: number) {
  vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
    const url = String(request)
    if (url.endsWith('/api/settings')) return json({ ui_scale: scale, navigation_order: ['/', '/accounts', '/groups', '/inbox', '/success', '/failed', '/logs'] })
    if (url.endsWith('/api/dashboard')) return json({ work_state: 'empty', metrics: { active_accounts: 0, remaining: 0, processing: 0, success: 0, failed: 0, unread: 0 }, events: [] })
    throw new Error(`Unexpected request: ${url}`)
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><Shell><div data-testid="child">content</div></Shell></MemoryRouter></QueryClientProvider>)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Shell v0.4.9 viewport and scale', () => {
  it('keeps sidebar and topbar outside the scaled work root and high scale never pre-shrinks the canvas', async () => {
    renderShell(3)
    const root = await screen.findByTestId('work-scale-root')
    expect(root).toHaveStyle({ zoom: '3', width: '100%', height: '100%' })
    expect(root.closest('main')).not.toBeNull()
    expect(document.querySelector('.sidebar')?.contains(root)).toBe(false)
    expect(document.querySelector('.window-bar')?.contains(root)).toBe(false)
  })

  it('compensates only sub-100% scale so the working area still fills its viewport', async () => {
    renderShell(0.75)
    const root = await screen.findByTestId('work-scale-root')
    expect(root.style.zoom).toBe('0.75')
    expect(parseFloat(root.style.width)).toBeCloseTo(133.333, 2)
    expect(parseFloat(root.style.height)).toBeCloseTo(133.333, 2)
  })

  it('uses the packaged application avatar without a broken img fallback glyph', async () => {
    renderShell(1)
    const mark = await screen.findByRole('img', { name: 'VK Search' })
    expect(mark).toHaveClass('brand-mark')
    expect(mark.tagName).toBe('DIV')
  })
})
