import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import InboxPage from './InboxPage'

const account = { id: 1, vk_user_id: 101, first_name: 'Иван', last_name: 'Иванов', display_name: 'Иван', profile_url: '', avatar_url: '', note: '', enabled: true, auth_status: 'ok', api_status: 'ok', session_status: 'ok', work_status: 'stopped', assigned_groups: 0, processed_count: 0, success_count: 0, failed_count: 0, unread_count: 0, last_checked_at: null, last_action_at: null, last_error: '' }
const dialog = { id: 10, account_id: 1, account_name: 'Иван', peer_id: -500, title: 'Сообщество', avatar_url: '', unread_count: 0, can_write: true, write_disabled_reason: '', last_message_at: null, is_pinned: false }

function json(value: unknown, status = 200) { return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }
function renderPage() { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return render(<QueryClientProvider client={client}><InboxPage /></QueryClientProvider>) }
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('offers user-created quick replies without auto-sending and supports dialog pinning', async () => {
  const calls: Array<{url: string, method: string, body?: string}> = []
  vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
    const url = String(request); const method = init?.method || 'GET'; calls.push({ url, method, body: init?.body?.toString() })
    if (url.endsWith('/api/accounts')) return json([account])
    if (url.includes('/api/inbox/dialogs?')) return json([dialog])
    if (url.endsWith('/api/quick-replies') && method === 'GET') return json([{ id: 'q1', text: 'Можно статистику?' }])
    if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 0, fetched: 0, total: 0, next_offset: 0, has_more: false })
    if (url.endsWith('/api/inbox/dialogs/10?limit=50')) return json({ dialog, reply_account: { id: 1, name: 'Иван', note: '', avatar_url: '' }, messages: [], local_total: 0, has_older_local: false, next_before_vk_message_id: null })
    if (url.endsWith('/api/inbox/dialogs/10') && method === 'PATCH') return json({ ...dialog, is_pinned: true })
    return json({ ok: true })
  }))
  renderPage()
  const row = await screen.findByRole('button', { name: /Сообщество/ })
  fireEvent.contextMenu(row)
  const pin = await screen.findByRole('button', { name: 'Закрепить' })
  fireEvent.click(pin)
  await waitFor(() => expect(calls.some(call => call.url.endsWith('/api/inbox/dialogs/10') && call.method === 'PATCH')).toBe(true))
  fireEvent.click(row)
  fireEvent.click(await screen.findByRole('button', { name: 'Быстрый ответ' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Можно статистику?' }))
  expect(screen.getByRole('textbox', { name: 'Ответ' })).toHaveValue('Можно статистику?')
  expect(calls.some(call => call.url.endsWith('/api/inbox/dialogs/10/reply') && call.method === 'POST')).toBe(false)
  expect(screen.queryByText('Архив')).not.toBeInTheDocument()
})
