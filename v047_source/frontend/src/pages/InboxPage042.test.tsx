import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import InboxPage from './InboxPage'

const account = {
  id: 1, vk_user_id: 101, first_name: 'Иван', last_name: 'Иванов', display_name: 'Иван Иванов',
  profile_url: 'https://vk.com/id101', avatar_url: '', note: '', enabled: true,
  auth_status: 'ok', api_status: 'ok', session_status: 'ok', work_status: 'working',
  assigned_groups: 0, processed_count: 0, success_count: 0, failed_count: 0, unread_count: 0,
  last_checked_at: null, last_action_at: null, last_error: '',
}

const dialog = {
  id: 10, account_id: 1, account_name: 'Иван Иванов', peer_id: -500, title: 'Тестовое сообщество',
  avatar_url: '', unread_count: 0, can_write: true, write_disabled_reason: '', last_message_at: '2026-08-26T10:00:00',
}

const payload = {
  dialog,
  reply_account: { id: 1, name: 'Иван Иванов', note: '', avatar_url: '' },
  messages: [{ id: 1000, vk_message_id: 1000, from_id: -500, outgoing: false, body: 'Привет', sent_at: '2026-08-26T10:00:00', is_read: true }],
  local_total: 1,
  has_older_local: false,
  next_before_vk_message_id: 1000,
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><InboxPage /></QueryClientProvider>)
}

describe('InboxPage v0.4.2', () => {
  it('opens a dialog with only the latest 50 messages', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'; calls.push(`${method} ${url}`)
      if (url.endsWith('/api/accounts')) return json([account])
      if (url.includes('/api/inbox/dialogs?')) return json([dialog])
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 1, fetched: 1, total: 1, next_offset: 1, has_more: false })
      if (url.endsWith('/api/inbox/dialogs/10?limit=50') && method === 'GET') return json(payload)
      return json({ ok: true })
    }))

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))

    await waitFor(() => expect(calls).toContain('POST /api/inbox/dialogs/10/sync?offset=0&count=50'))
    await waitFor(() => expect(calls).toContain('GET /api/inbox/dialogs/10?limit=50'))
    expect(calls.some(call => call.includes('count=300'))).toBe(false)
  })

  it('does not claim success when VK returns ok=false and keeps the draft', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'
      if (url.endsWith('/api/accounts')) return json([account])
      if (url.includes('/api/inbox/dialogs?')) return json([dialog])
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 1, fetched: 1, total: 1, next_offset: 1, has_more: false })
      if (url.endsWith('/api/inbox/dialogs/10?limit=50') && method === 'GET') return json(payload)
      if (url.endsWith('/api/inbox/dialogs/10/reply') && method === 'POST') return json({ ok: false, state: 'auth_required', error: 'VK требует повторную авторизацию', account_id: 1 })
      return json({ ok: true })
    }))

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))
    const box = await screen.findByRole('textbox', { name: 'Ответ' })
    fireEvent.change(box, { target: { value: 'Тестовое сообщение' } })
    fireEvent.click(screen.getByRole('button', { name: /Отправить/ }))

    await waitFor(() => expect(screen.getByRole('textbox', { name: 'Ответ' })).toHaveValue('Тестовое сообщение'))
    expect(screen.queryByText('Сообщение отправлено от правильного аккаунта')).not.toBeInTheDocument()
  })
})
