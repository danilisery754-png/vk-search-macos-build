import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccountsPage, { moveVisualAccountOrder, normalizeVisualAccountOrder } from './AccountsPage'

const rows = [1, 2, 3].map(id => ({
  id, vk_user_id: 100 + id, first_name: `Имя${id}`, last_name: '', display_name: `Аккаунт ${id}`,
  profile_url: '', avatar_url: '', note: '', enabled: true, auth_status: 'ok', api_status: 'ok', session_status: 'ok', work_status: 'stopped',
  health_status: 'alive', health_detail: '', assigned_groups: 0, processed_count: 0, success_count: 0, failed_count: 0, unread_count: 0,
  last_checked_at: null, last_action_at: null, last_error: '',
}))

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
    const url = String(request); const method = init?.method || 'GET'
    if (url.endsWith('/api/accounts') && method === 'GET') return json(rows)
    if (url.endsWith('/api/accounts/health/check') && method === 'POST') return json(rows)
    if (url.includes('/api/accounts/') && method === 'PATCH') return json({ ok: true })
    throw new Error(`Unexpected request: ${method} ${url}`)
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><AccountsPage /></QueryClientProvider>)
}

function cardNames() {
  return screen.getAllByTestId('account-card').map(card => within(card).getByRole('heading').textContent)
}

beforeEach(() => localStorage.clear())
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('AccountsPage v0.4.9 visual order', () => {
  it('normalizes saved IDs, removes stale IDs and appends newly added accounts at the bottom', () => {
    expect(normalizeVisualAccountOrder([3, 99, 1], [1, 2, 3, 4])).toEqual([3, 1, 2, 4])
  })

  it('moves only the visual ID order with natural shifting', () => {
    expect(moveVisualAccountOrder([1, 2, 3, 4, 5], 2, 5)).toEqual([1, 3, 4, 5, 2])
    expect(moveVisualAccountOrder([1, 2, 3], 2, 1)).toEqual([2, 1, 3])
  })

  it('restores visual order from localStorage without changing account data', async () => {
    localStorage.setItem('vk-search.accounts.visual-order.v1', JSON.stringify([3, 1, 2]))
    renderPage()
    await waitFor(() => expect(screen.getAllByTestId('account-card')).toHaveLength(3))
    expect(cardNames()).toEqual(['Аккаунт 3', 'Аккаунт 1', 'Аккаунт 2'])
    expect(within(screen.getAllByTestId('account-card')[0]).getByText('VK ID 103')).toBeInTheDocument()
  })

  it('requires about 250 ms hold before a card is draggable and interactive controls stay clickable', async () => {
    vi.useFakeTimers()
    renderPage()
    await act(async () => { await Promise.resolve() })
    const card = screen.getAllByTestId('account-card')[0]
    const freeArea = within(card).getByRole('heading', { name: 'Аккаунт 1' })
    fireEvent.pointerDown(freeArea, { clientX: 10, clientY: 10, button: 0 })
    act(() => vi.advanceTimersByTime(249))
    expect(card).toHaveAttribute('draggable', 'false')
    act(() => vi.advanceTimersByTime(1))
    expect(card).toHaveAttribute('draggable', 'true')
    fireEvent.pointerUp(freeArea)
    expect(card).toHaveAttribute('draggable', 'false')

    const menu = within(card).getByRole('button', { name: 'Меню аккаунта Аккаунт 1' })
    fireEvent.pointerDown(menu)
    act(() => vi.advanceTimersByTime(300))
    expect(card).toHaveAttribute('draggable', 'false')
    fireEvent.click(menu)
    expect(await within(card).findByRole('menu')).toBeInTheDocument()
  })

  it('does not reorder during dragover and persists only after drop', async () => {
    localStorage.setItem('vk-search.accounts.visual-order.v1', JSON.stringify([1, 2, 3]))
    renderPage()
    await waitFor(() => expect(screen.getAllByTestId('account-card')).toHaveLength(3))
    const cards = screen.getAllByTestId('account-card')
    fireEvent.dragOver(cards[2])
    expect(cardNames()).toEqual(['Аккаунт 1', 'Аккаунт 2', 'Аккаунт 3'])
    fireEvent.drop(cards[2], { dataTransfer: { getData: () => '1' } })
    expect(cardNames()).toEqual(['Аккаунт 2', 'Аккаунт 3', 'Аккаунт 1'])
    expect(JSON.parse(localStorage.getItem('vk-search.accounts.visual-order.v1') || '[]')).toEqual([2, 3, 1])
  })
})
