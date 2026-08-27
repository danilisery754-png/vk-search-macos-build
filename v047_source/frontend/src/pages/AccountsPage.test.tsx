import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AccountsPage from './AccountsPage'

const account = (id = 1, health_status = 'alive') => ({
  id, vk_user_id: 1000 + id, first_name: 'Иван', last_name: 'Иванов', display_name: `Иван Иванов ${id}`,
  profile_url: `https://vk.com/id${1000 + id}`, avatar_url: '', note: '', enabled: true,
  auth_status: 'ok', api_status: 'ok', session_status: 'ok', work_status: 'working',
  health_status, health_checked_at: '2026-08-27T13:00:00+00:00', health_detail: 'Проверено VK API',
  assigned_groups: 3, processed_count: 2, success_count: 1, failed_count: 1, unread_count: 4,
  last_checked_at: null, last_action_at: null, last_error: '',
})

afterEach(() => vi.unstubAllGlobals())

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><AccountsPage /></QueryClientProvider>)
}

describe('AccountsPage', () => {
  it('shows explicit login confirmation and does not request token flow before the click', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'; calls.push(`${method} ${url}`)
      if (url.endsWith('/api/accounts') && method === 'GET') return json([])
      if (url.endsWith('/api/accounts/authorize') && method === 'POST') return json({ id: 'job-1', state: 'created', message: 'Подготовка', account_id: null, error: '' }, 202)
      if (url.endsWith('/api/accounts/authorize/job-1') && method === 'GET') return json({ id: 'job-1', state: 'waiting_user', message: 'Войдите в VK и нажмите кнопку', account_id: null, error: '' })
      if (url.endsWith('/api/accounts/authorize/job-1/confirm') && method === 'POST') return json({ id: 'job-1', state: 'user_confirmed', message: 'Получаю токен VK', account_id: null, error: '' })
      throw new Error(`Unexpected request: ${method} ${url}`)
    }))
    renderPage()
    fireEvent.click((await screen.findAllByRole('button', { name: /Подключить аккаунт/i }))[0])
    const ready = await screen.findByRole('button', { name: 'Я вошёл в VK' })
    expect(calls.some(call => call.includes('/confirm'))).toBe(false)
    fireEvent.click(ready)
    await waitFor(() => expect(calls).toContain('POST /api/accounts/authorize/job-1/confirm'))
  })

  it('hides diagnostics and opens a functional account menu', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request)
      if (url.endsWith('/api/accounts')) return json([account()])
      return json({ ok: true })
    }))
    renderPage()
    await screen.findByText('Иван Иванов 1')
    expect(screen.queryByText('В работе')).not.toBeInTheDocument()
    expect(screen.queryByText('Обработано')).not.toBeInTheDocument()
    expect(screen.queryByText('Авторизация')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Меню аккаунта Иван Иванов 1' }))
    expect(screen.getByRole('menu')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Открыть сообщения/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Обновить вход/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Удалить аккаунт/ })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('shows account health without confusing temporary failures with a block', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'
      if (url.endsWith('/api/accounts') && method === 'GET') return json([account(1, 'alive'), account(2, 'unknown')])
      if (url.endsWith('/api/accounts/health/check') && method === 'POST') return json([account(1, 'alive'), account(2, 'unknown')])
      return json({ ok: true })
    }))
    renderPage()
    expect(await screen.findByText('Живой')).toBeInTheDocument()
    expect(await screen.findByText('Не удалось проверить')).toBeInTheDocument()
    expect(screen.queryByText('Заблокирован')).not.toBeInTheDocument()
  })

  it('contains 100 accounts inside a dedicated scroll owner', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'
      if (url.endsWith('/api/accounts') && method === 'GET') return json(Array.from({ length: 100 }, (_, i) => account(i + 1)))
      if (url.endsWith('/api/accounts/health/check') && method === 'POST') return json(Array.from({ length: 100 }, (_, i) => account(i + 1)))
      return json({ ok: true })
    }))
    renderPage()
    expect(await screen.findAllByTestId('account-card')).toHaveLength(100)
    expect(screen.getByTestId('accounts-scroll')).toBeInTheDocument()
  })
})
