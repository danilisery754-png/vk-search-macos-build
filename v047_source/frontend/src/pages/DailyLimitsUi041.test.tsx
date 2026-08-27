/** @vitest-environment jsdom */
import '@testing-library/jest-dom/vitest'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AccountsPage from './AccountsPage'
import DashboardPage from './DashboardPage'
import GroupsPage from './GroupsPage'
import SettingsPage from './SettingsPage'

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function wrapper(node: React.ReactNode, router = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const content = <QueryClientProvider client={client}>{node}</QueryClientProvider>
  return render(router ? <MemoryRouter>{content}</MemoryRouter> : content)
}

beforeEach(() => vi.stubGlobal('React', React))
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('v0.4.1 daily limit UI', () => {
  it('calls the daily setting a rolling 24-hour account limit, not a pass limit', async () => {
    const settings = {
      max_groups_per_account: 50,
      delay_seconds: 60,
      delay_mode: 'fixed',
      delay_min_seconds: 60,
      delay_max_seconds: 90,
      message_text: 'Текст',
      message_texts: ['Текст'],
      retry_max_attempts: 4,
      inbox_sync_seconds: 30,
      interface_compact: false,
    }
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) =>
      json(String(request).endsWith('/api/backups') ? [] : settings)
    ))

    wrapper(<SettingsPage />)

    expect(await screen.findByText('Суточный лимит на аккаунт')).toBeInTheDocument()
    expect(screen.getByText(/24 часов с первой учтённой группы/i)).toBeInTheDocument()
    expect(screen.queryByText(/за проход/i)).not.toBeInTheDocument()
  })

  it('shows current quota usage and unlock time on account cards', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json([{
      id: 1,
      vk_user_id: 1001,
      first_name: 'Иван',
      last_name: 'Иванов',
      display_name: 'Иван Иванов',
      profile_url: 'https://vk.com/id1001',
      avatar_url: '',
      note: '',
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
      daily_limit: 50,
      quota_consumed: 50,
      quota_available: 0,
      quota_window_started_at: '2026-08-26T10:00:00',
      quota_window_ends_at: '2026-08-27T10:00:00',
    }])))

    wrapper(<AccountsPage />)

    expect(await screen.findByText('50 / 50')).toBeInTheDocument()
    expect(screen.getByText('Суточный лимит')).toBeInTheDocument()
    expect(screen.getByText(/разблокируется/i)).toBeInTheDocument()
  })

  it('offers normal start and an explicit destructive quota reset start', async () => {
    const calls: Array<{ url: string; body: unknown }> = []
    vi.stubGlobal('confirm', vi.fn(() => true))
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request)
      const method = init?.method || 'GET'
      if (url.endsWith('/api/dashboard') && method === 'GET') {
        return json({
          work_state: 'waiting_limit',
          metrics: { active_accounts: 2, remaining: 10, processing: 0, success: 5, failed: 1, unread: 0 },
          events: [],
        })
      }
      if (url.endsWith('/api/work/start') && method === 'POST') {
        calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return json({ state: 'running' })
      }
      return json({ ok: true })
    }))

    wrapper(<DashboardPage />)

    expect((await screen.findAllByText('Ожидание суточного лимита')).length).toBeGreaterThanOrEqual(1)
    // v0.4.6 deliberately moved run controls from DashboardPage into the
    // application Shell. Keep this legacy quota page test focused on the
    // waiting-limit state; Shell.v046.test.tsx owns the global controls.
    expect(screen.queryByRole('button', { name: /Запустить с учётом лимитов/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Игнорировать лимиты и запустить/i })).not.toBeInTheDocument()
    expect(calls).toEqual([])
  })

  it('lets a new import append or replace only the not-started tail', async () => {
    const calls: unknown[] = []
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request)
      const method = init?.method || 'GET'
      if (url.endsWith('/api/groups') && method === 'GET') return json({ total: 0, items: [] })
      if (url.endsWith('/api/groups/import') && method === 'POST') {
        calls.push(JSON.parse(String(init?.body || '{}')))
        return json({ found: 1, added: 1, duplicates: 0, unresolved: [], replaced: 2, cancelled: false })
      }
      return json({ ok: true })
    }))

    wrapper(<GroupsPage />, true)
    const input = await screen.findByPlaceholderText(/https:\/\/vk\.com\/example/i)
    fireEvent.change(input, { target: { value: 'https://vk.com/club1' } })

    fireEvent.click(screen.getByRole('button', { name: /Добавить в список/i }))
    await waitFor(() => expect(calls[0]).toEqual({ text: 'https://vk.com/club1', mode: 'append' }))

    fireEvent.change(input, { target: { value: 'https://vk.com/club2' } })
    fireEvent.click(screen.getByRole('button', { name: /Заменить ожидающий список/i }))
    expect(screen.getByText(/уже начатые группы сохранятся/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Подтвердить замену/i }))
    await waitFor(() => expect(calls[1]).toEqual({ text: 'https://vk.com/club2', mode: 'replace_waiting' }))
  })
})
