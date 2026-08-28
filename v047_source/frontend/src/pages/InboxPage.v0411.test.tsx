import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SessionUiStoreProvider } from '../components/SessionUiStore'
import InboxPage from './InboxPage'

const account = {
  id: 1,
  vk_user_id: 101,
  first_name: 'Иван',
  last_name: 'Иванов',
  display_name: 'Иван Иванов',
  profile_url: 'https://vk.com/id101',
  avatar_url: '',
  note: 'Основной аккаунт',
  enabled: true,
  auth_status: 'ok',
  api_status: 'ok',
  session_status: 'ok',
  work_status: 'stopped',
  assigned_groups: 0,
  processed_count: 0,
  success_count: 0,
  failed_count: 0,
  unread_count: 0,
  last_checked_at: null,
  last_action_at: null,
  last_error: '',
}

const dialog = {
  id: 10,
  account_id: 1,
  account_name: 'Иван Иванов',
  peer_id: 500,
  title: 'Тестовый диалог',
  avatar_url: '',
  unread_count: 0,
  can_write: true,
  write_disabled_reason: '',
  last_message_at: '2026-08-28T10:00:00',
  last_message_preview: 'Привет',
  last_message_outgoing: false,
  last_message_deleted: false,
  is_archived: false,
  archived_at: null,
  is_pinned: false,
  pinned_at: null,
  folder_ids: [],
}

const message = {
  account_id: 1,
  dialog_id: 10,
  vk_message_id: 700,
  from_id: 500,
  outgoing: false,
  body: 'Привет',
  sent_at: '2026-08-28T10:00:00',
  updated_at: null,
  deleted: false,
  is_read: true,
  attachments: [],
  reply_message: null,
  forwarded_messages: [],
}

function json(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function stubApi() {
  return vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
    const url = String(request)
    const method = String(init?.method || 'GET').toUpperCase()
    if (url.endsWith('/api/accounts')) return json([account])
    if (url.includes('/api/inbox/folders')) return json([])
    if (url.includes('/api/inbox/dialogs?')) return json([dialog])
    if (url.endsWith('/api/inbox/dialogs/10?limit=50')) return json({
      dialog,
      reply_account: { id: 1, name: 'Иван Иванов', note: 'Основной аккаунт', avatar_url: '' },
      messages: [message],
      local_total: 1,
      next_before_vk_message_id: null,
      has_older_local: false,
    })
    if (url.endsWith('/api/inbox/dialogs/10/sync?offset=0&count=50') && method === 'POST') return json({ ok: true, messages: 1, fetched: 1, total: 1, next_offset: 1, has_more: false })
    if (url.includes('/api/quick-replies')) return json([])
    if (url.includes('/activity') && method === 'POST') return json({ ok: true })
    if (url.includes('/reply') && method === 'POST') return json({ ok: true, message_id: 99, account_id: 1 })
    return json({ ok: true })
  })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/inbox']}>
        <SessionUiStoreProvider>
          <div id="app-overlay-root" />
          <InboxPage />
        </SessionUiStoreProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('InboxPage v0.4.11 polish', () => {
  it('uses account note as the group label and keeps collapse/expand separate from the drag handle', async () => {
    vi.stubGlobal('fetch', stubApi())
    renderPage()

    const toggle = await screen.findByRole('button', { name: /Основной аккаунт/ })
    const group = toggle.closest('.dialog-group') as HTMLElement
    expect(group).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Перетащить аккаунт Основной аккаунт' })).toBeInTheDocument()
    expect(within(group).getByRole('button', { name: /Тестовый диалог/ })).toBeInTheDocument()

    fireEvent.click(toggle)
    await waitFor(() => expect(group).toHaveClass('dialog-group--collapsed'))
    expect(within(group).queryByRole('button', { name: /Тестовый диалог/ })).not.toBeInTheDocument()

    fireEvent.click(toggle)
    await waitFor(() => expect(group).not.toHaveClass('dialog-group--collapsed'))
    expect(within(group).getByRole('button', { name: /Тестовый диалог/ })).toBeInTheDocument()
  })

  it('removes the duplicate sender strip and keeps emoji, quick replies and an icon-only send action', async () => {
    vi.stubGlobal('fetch', stubApi())
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Тестовый диалог/ }))
    const textarea = await screen.findByRole('textbox', { name: 'Ответ' })
    expect(textarea).toBeInTheDocument()

    const topIdentity = screen.getByText('Вы отвечаете от:').closest('.reply-identity') as HTMLElement
    expect(within(topIdentity).getByText('Основной аккаунт')).toBeInTheDocument()
    expect(document.querySelector('.reply-account')).toBeNull()

    const controls = screen.getByTestId('composer-controls')
    expect(within(controls).getByRole('button', { name: 'Смайлики' })).toBeInTheDocument()
    expect(within(controls).getByRole('button', { name: 'Быстрые ответы' })).toBeInTheDocument()
    const send = within(controls).getByRole('button', { name: 'Отправить' })
    expect(send.textContent?.trim()).toBe('')
    expect(send.querySelector('svg')).not.toBeNull()
  })
})
