import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import Shell from './Shell'

function json(value: unknown) {
  return new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
}

function renderShell() {
  vi.stubGlobal('fetch', vi.fn(async (request: RequestInfo | URL) => {
    const url = String(request)
    if (url.endsWith('/api/dashboard')) return json({ work_state: 'stopped', metrics: { active_accounts: 1, remaining: 2, processing: 0, success: 0, failed: 0, unread: 0 }, events: [] })
    if (url.endsWith('/api/settings')) return json({ navigation_order: ['/', '/accounts', '/groups', '/inbox', '/success', '/failed', '/logs'] })
    return json({})
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><Shell><div>page</div></Shell></MemoryRouter></QueryClientProvider>)
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('uses the approved default navigation order and global work controls', async () => {
  renderShell()
  const links = await screen.findAllByRole('link')
  const primary = links.map(link => link.textContent?.trim()).filter(Boolean).slice(0, 7)
  expect(primary).toEqual(['Главная', 'Аккаунты', 'Список групп', 'Сообщения', 'Успешно написали', 'Не удалось написать', 'Логи'])
  expect(screen.getByRole('button', { name: 'Запустить' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Без лимитов' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Пауза' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Продолжить' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Остановить' })).toBeInTheDocument()
})
