import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from './SettingsPage'

const settings = {
  max_groups_per_account: 50,
  delay_seconds: 60,
  delay_mode: 'fixed',
  delay_min_seconds: 60,
  delay_max_seconds: 90,
  message_text: 'Общий первый',
  suggested_post_text: 'Общий первый',
  message_texts: ['Общий первый', 'Общий второй'],
  suggested_post_texts: ['Общий первый', 'Общий второй'],
  retry_min_attempts: 1,
  retry_max_attempts: 4,
  inbox_sync_seconds: 30,
  ui_scale: 1,
}

afterEach(() => vi.unstubAllGlobals())

describe('SettingsPage', () => {
  it('keeps one shared outreach editor in sending settings and uses suggested posts only as fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request)
      return new Response(JSON.stringify(url.endsWith('/backups') ? [] : settings), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>)

    await waitFor(() => expect(screen.getAllByRole('textbox')).toHaveLength(2))
    expect(screen.getAllByRole('button', { name: 'Добавить вариант' })).toHaveLength(1)
    expect(screen.getByText('Один общий текст: сначала ЛС, предложка используется как запасной способ')).toBeInTheDocument()
  })

  it('keeps many message variants inside a bounded settings region', async () => {
    const many = { ...settings, message_texts: Array.from({ length: 30 }, (_, i) => `Текст ${i + 1}`) }
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request)
      return new Response(JSON.stringify(url.endsWith('/backups') ? [] : many), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>)
    await waitFor(() => expect(screen.getAllByRole('textbox')).toHaveLength(30))
    const content = container.querySelector<HTMLElement>('.settings-content')
    expect(content).toHaveClass('settings-content--bounded')
    expect(content).not.toBeNull()
    if (!content) throw new Error('Settings content is missing')
    content.scrollTop = 200
    fireEvent.click(screen.getByRole('tab', { name: 'Дополнительно' }))
    expect(content.scrollTop).toBe(0)
  })

  it('keeps message synchronization under the Messages tab', async () => {
    vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
      const url = String(request)
      return new Response(JSON.stringify(url.endsWith('/backups') ? [] : settings), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><SettingsPage /></QueryClientProvider>)
    fireEvent.click(screen.getByRole('tab', { name: 'Сообщения' }))
    expect(await screen.findByText('Синхронизация сообщений, секунд')).toBeInTheDocument()
  })
})
