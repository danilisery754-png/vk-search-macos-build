import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import InboxPage from './InboxPage'

const account = {
  id: 1, vk_user_id: 101, first_name: 'Иван', last_name: 'Иванов', display_name: 'Иван Иванов',
  profile_url: '', avatar_url: '', note: '', enabled: true, auth_status: 'ok', api_status: 'ok', session_status: 'ok', work_status: 'stopped',
  assigned_groups: 0, processed_count: 0, success_count: 0, failed_count: 0, unread_count: 0,
  last_checked_at: null, last_action_at: null, last_error: '',
}

const baseDialog = {
  id: 10, account_id: 1, account_name: 'Иван Иванов', peer_id: 500, title: 'Пётр', avatar_url: '', unread_count: 3,
  can_write: true, write_disabled_reason: '', last_message_at: '2026-08-27T17:40:00',
  last_message_preview: 'привет, хотел уточнить очень длинный текст сообщения', last_message_outgoing: true,
  last_message_deleted: false, is_archived: false, archived_at: null, is_pinned: false, pinned_at: null, folder_ids: [],
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><InboxPage /></QueryClientProvider>)
}

function stubBase(dialogs = [baseDialog]) {
  return vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
    const url = String(request); const method = init?.method || 'GET'
    if (url.endsWith('/api/accounts')) return json([account])
    if (url.includes('/api/inbox/folders')) return json([])
    if (url.includes('/api/inbox/archive')) return json(dialogs.map(row => ({ ...row, is_archived: true })))
    if (url.includes('/api/inbox/dialogs?')) return json(dialogs)
    if (url.includes('/api/quick-replies')) return json([])
    if (url.endsWith('/api/inbox/dialogs/10/archive') && method === 'POST') return json({ ok: true, id: 10, is_archived: true })
    if (url.endsWith('/api/inbox/dialogs/10/restore') && method === 'POST') return json({ ok: true, id: 10, is_archived: false })
    return json({ ok: true })
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('InboxPage v0.4.9', () => {
  it('shows All, Unread and Archive filters and fetches archive separately', async () => {
    const fetchMock = stubBase()
    vi.stubGlobal('fetch', fetchMock)
    renderPage()
    expect(await screen.findByRole('button', { name: 'Все' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Непрочитанные' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Архив' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([request]) => String(request).includes('/api/inbox/archive'))).toBe(true))
  })

  it('renders outgoing last-message preview with time and a one-line preview element', async () => {
    vi.stubGlobal('fetch', stubBase())
    renderPage()
    const dialogButton = await screen.findByRole('button', { name: /Пётр/ })
    expect(within(dialogButton).getByText(/Вы: привет, хотел уточнить/)).toHaveClass('dialog-preview')
    expect(dialogButton.querySelector('time')).not.toBeNull()
  })

  it('formats deleted incoming and outgoing previews exactly as approved', async () => {
    const dialogs = [
      { ...baseDialog, id: 11, peer_id: 501, title: 'Входящий', unread_count: 0, last_message_outgoing: false, last_message_deleted: true, last_message_preview: 'старый текст' },
      { ...baseDialog, id: 12, peer_id: 502, title: 'Исходящий', unread_count: 0, last_message_outgoing: true, last_message_deleted: true, last_message_preview: 'секретный текст' },
    ]
    vi.stubGlobal('fetch', stubBase(dialogs))
    renderPage()
    expect(await screen.findByText('Сообщение удалено · старый текст')).toBeInTheDocument()
    expect(screen.getByText('Вы: Сообщение удалено')).toBeInTheDocument()
    expect(screen.queryByText(/секретный текст/)).not.toBeInTheDocument()
  })

  it('archives by context menu and archive view has no unread badge', async () => {
    const fetchMock = stubBase()
    vi.stubGlobal('fetch', fetchMock)
    renderPage()
    const dialogButton = await screen.findByRole('button', { name: /Пётр/ })
    fireEvent.contextMenu(dialogButton)
    fireEvent.click(await screen.findByRole('button', { name: 'В архив' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([request, init]) => String(request).endsWith('/api/inbox/dialogs/10/archive') && init?.method === 'POST')).toBe(true))
    fireEvent.click(screen.getByRole('button', { name: 'Архив' }))
    const archivedButton = await screen.findByRole('button', { name: /Пётр/ })
    expect(archivedButton.querySelector('.dialog-unread')).toBeNull()
    fireEvent.contextMenu(archivedButton)
    expect(await screen.findByRole('button', { name: 'Вернуть из архива' })).toBeInTheDocument()
  })

  it('stacks emoji, quick replies and send controls in that order and keeps quick action icon-only', async () => {
    vi.stubGlobal('fetch', stubBase())
    renderPage()
    const dialogButton = await screen.findByRole('button', { name: /Пётр/ })
    fireEvent.click(dialogButton)
    const composer = await screen.findByTestId('composer-controls')
    const buttons = within(composer).getAllByRole('button')
    expect(buttons[0]).toHaveAccessibleName('Смайлики')
    expect(buttons[1]).toHaveAccessibleName('Быстрые ответы')
    expect(buttons[1]).not.toHaveTextContent('Быстрый ответ')
    expect(buttons[buttons.length - 1]).toHaveTextContent('Отправить')
  })
})
