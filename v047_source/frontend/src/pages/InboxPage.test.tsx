import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import InboxPage from './InboxPage'

const account = {
  id: 1, vk_user_id: 101, first_name: 'Иван', last_name: 'Иванов', display_name: 'Иван Иванов',
  profile_url: 'https://vk.com/id101', avatar_url: '/avatar.jpg', note: 'Основной аккаунт', enabled: true,
  auth_status: 'ok', api_status: 'ok', session_status: 'ok', work_status: 'working',
  assigned_groups: 0, processed_count: 0, success_count: 0, failed_count: 0, unread_count: 0,
  last_checked_at: null, last_action_at: null, last_error: '',
}

const dialog = {
  id: 10, account_id: 1, account_name: 'Иван Иванов', peer_id: -500, title: 'Тестовое сообщество',
  avatar_url: '', unread_count: 0, can_write: true, write_disabled_reason: '', last_message_at: '2026-08-25T12:00:00',
}

function message(id: number) {
  return { id, vk_message_id: id, from_id: -500, outgoing: id % 2 === 0, body: `Сообщение ${id}`, sent_at: '2026-08-25T12:00:00', is_read: true }
}

function payload(overrides: Record<string, unknown> = {}) {
  return {
    dialog: { ...dialog },
    reply_account: { id: 1, name: 'Иван Иванов', note: 'Основной аккаунт', avatar_url: '/avatar.jpg' },
    messages: [message(998), message(999), message(1000)],
    local_total: 3,
    has_older_local: false,
    next_before_vk_message_id: 998,
    ...overrides,
  }
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><InboxPage /></QueryClientProvider>)
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('InboxPage v0.4.0', () => {
  it('automatically syncs a selected dialog and shows reply identity', async () => {
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'; calls.push(`${method} ${url}`)
      if (url.endsWith('/api/accounts') && method === 'GET') return json([account])
      if (url.includes('/api/inbox/dialogs?') && method === 'GET') return json([dialog])
      if (url.endsWith('/api/inbox/dialogs/10/read') && method === 'POST') return json({ ok: true })
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 3, fetched: 3, total: 3, next_offset: 3, has_more: false })
      if (url.endsWith('/api/inbox/dialogs/10?limit=50') && method === 'GET') return json(payload())
      throw new Error(`Unexpected request: ${method} ${url}`)
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))
    await waitFor(() => expect(calls).toContain('POST /api/inbox/dialogs/10/sync?offset=0&count=50'))
    await waitFor(() => expect(calls).toContain('GET /api/inbox/dialogs/10?limit=50'))
    const replyIdentityLabel = await screen.findByText('Вы отвечаете от:')
    expect(replyIdentityLabel).toBeInTheDocument()
    const replyIdentity = replyIdentityLabel.closest('.reply-identity')
    expect(replyIdentity).not.toBeNull()
    expect(within(replyIdentity as HTMLElement).getByText('Основной аккаунт')).toBeInTheDocument()
    expect(screen.getByAltText('Иван Иванов')).toHaveAttribute('src', '/avatar.jpg')
    expect(screen.getByRole('textbox', { name: 'Ответ' })).toBeInTheDocument()
  })

  it('keeps history visible but hides the composer when VK forbids replies', async () => {
    const blocked = { ...dialog, can_write: false, write_disabled_reason: '7' }
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'
      if (url.endsWith('/api/accounts')) return json([account])
      if (url.includes('/api/inbox/dialogs?')) return json([blocked])
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 1, fetched: 1, total: 1, next_offset: 1, has_more: false })
      if (url.endsWith('/api/inbox/dialogs/10?limit=50')) return json(payload({ dialog: blocked, messages: [message(1000)] }))
      return json({ ok: true })
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))
    expect(await screen.findByText('Сообщение 1000')).toBeInTheDocument()
    expect(screen.getByText('Отправка сообщений в этот диалог недоступна')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: 'Ответ' })).not.toBeInTheDocument()
  })

  it('loads an older local page near the top before asking VK for more', async () => {
    const calls: string[] = []
    let releaseOlder!: () => void
    const olderGate = new Promise<void>(resolve => { releaseOlder = resolve })
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'; calls.push(`${method} ${url}`)
      if (url.endsWith('/api/accounts')) return json([account])
      if (url.includes('/api/inbox/dialogs?') && !url.includes('/10?')) return json([dialog])
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 300, fetched: 300, total: 900, next_offset: 300, has_more: true })
      if (url.endsWith('/api/inbox/dialogs/10?limit=50')) return json(payload({ messages: [message(700), message(701), message(702)], local_total: 500, has_older_local: true, next_before_vk_message_id: 700 }))
      if (url.endsWith('/api/inbox/dialogs/10?limit=200&before_vk_message_id=700')) { await olderGate; return json(payload({ messages: [message(500), message(501)], local_total: 500, has_older_local: false, next_before_vk_message_id: 500 })) }
      return json({ ok: true })
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))
    const scroller = await screen.findByTestId('messages-scroll')
    Object.defineProperty(scroller, 'scrollTop', { configurable: true, writable: true, value: 20 })
    fireEvent.scroll(scroller)
    fireEvent.scroll(scroller)
    await waitFor(() => expect(calls.filter(call => call === 'GET /api/inbox/dialogs/10?limit=200&before_vk_message_id=700')).toHaveLength(1))
    expect(calls.some(call => call.includes('sync?offset=300&count=200'))).toBe(false)
    releaseOlder()
    expect(await screen.findByText('Сообщение 500')).toBeInTheDocument()
  })

  it('refills local history from VK after the local cursor is exhausted', async () => {
    const calls: string[] = []
    let olderReads = 0
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'; calls.push(`${method} ${url}`)
      if (url.endsWith('/api/accounts')) return json([account])
      if (url.includes('/api/inbox/dialogs?') && !url.includes('/10?')) return json([dialog])
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 300, fetched: 300, total: 900, next_offset: 300, has_more: true })
      if (url.endsWith('/api/inbox/dialogs/10?limit=50')) return json(payload({ messages: [message(700), message(701)], local_total: 300, has_older_local: false, next_before_vk_message_id: 700 }))
      if (url.endsWith('/api/inbox/dialogs/10?limit=200&before_vk_message_id=700')) {
        olderReads += 1
        return olderReads === 1
          ? json(payload({ messages: [], local_total: 300, has_older_local: false, next_before_vk_message_id: null }))
          : json(payload({ messages: [message(500), message(501)], local_total: 500, has_older_local: false, next_before_vk_message_id: 500 }))
      }
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=300&count=200') && method === 'POST') return json({ ok: true, messages: 200, fetched: 200, total: 900, next_offset: 500, has_more: true })
      return json({ ok: true })
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))
    const scroller = await screen.findByTestId('messages-scroll')
    Object.defineProperty(scroller, 'scrollTop', { configurable: true, writable: true, value: 20 })
    fireEvent.scroll(scroller)
    await waitFor(() => expect(calls).toContain('POST /api/inbox/dialogs/10/sync?offset=300&count=200'))
    expect(await screen.findByText('Сообщение 500')).toBeInTheDocument()
  })

  it('does not force-scroll down when a new message arrives while reading older history', async () => {
    let latest = payload({ messages: [message(999), message(1000)], local_total: 2, next_before_vk_message_id: 999 })
    let latestSyncCalls = 0
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request); const method = init?.method || 'GET'
      if (url.endsWith('/api/accounts')) return json([account])
      if (url.includes('/api/inbox/dialogs?') && !url.includes('/10?')) return json([dialog])
      if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') { latestSyncCalls += 1; if (latestSyncCalls > 1) { latest = payload({ messages: [message(999), message(1000), message(1001)], local_total: 3, next_before_vk_message_id: 999 }); return json({ ok: true, messages: 3, fetched: 3, total: 3, next_offset: 3, has_more: false }) }; return json({ ok: true, messages: 2, fetched: 2, total: 2, next_offset: 2, has_more: false }) }
      if (url.endsWith('/api/inbox/dialogs/10?limit=50')) return json(latest)
      return json({ ok: true })
    }))
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Тестовое сообщество/ }))
    const scroller = await screen.findByTestId('messages-scroll')
    expect(await screen.findByText('Сообщение 1000')).toBeInTheDocument()
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
    Object.defineProperties(scroller, {
      scrollTop: { configurable: true, writable: true, value: 100 },
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 500 },
    })
    fireEvent.scroll(scroller)
    fireEvent.click(screen.getByRole('button', { name: 'Обновить диалог' }))
    expect(await screen.findByText('Сообщение 1001')).toBeInTheDocument()
    expect(scroller.scrollTop).toBe(100)
    expect(screen.getByRole('button', { name: 'Новые сообщения' })).toBeInTheDocument()
  })
})
