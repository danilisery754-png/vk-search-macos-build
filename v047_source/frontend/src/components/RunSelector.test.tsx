import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RunSelector from './RunSelector'

const runs = [
  { id: 2, state: 'completed', started_at: '2026-08-25T12:00:00', finished_at: '2026-08-25T12:10:00', original_count: 100, processed_count: 100, success_count: 80, failure_count: 20 },
  { id: 1, state: 'completed', started_at: '2026-08-24T12:00:00', finished_at: '2026-08-24T12:20:00', original_count: 50, processed_count: 50, success_count: 30, failure_count: 20 },
]

afterEach(() => vi.restoreAllMocks())

describe('RunSelector', () => {
  it('shows saved runs and marks an archived selection', () => {
    render(<RunSelector runs={runs} currentRunId={2} selectedRunId={1} onSelect={() => undefined} onDelete={() => undefined} />)
    expect(screen.getByRole('button', { name: /Запуски/ })).toBeInTheDocument()
    expect(screen.getByText(/Просмотр архива: запуск #1/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Вернуться к текущему запуску' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Запуски/ }))
    expect(screen.getByRole('menuitem', { name: /Запуск #2/ })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: /Запуск #1/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Удалить запуск #2' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Удалить запуск #1' })).toBeInTheDocument()
  })

  it('asks before deleting an archived run', () => {
    const onDelete = vi.fn()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<RunSelector runs={runs} currentRunId={2} selectedRunId={2} onSelect={() => undefined} onDelete={onDelete} />)
    fireEvent.click(screen.getByRole('button', { name: /Запуски/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Удалить запуск #1' }))
    expect(window.confirm).toHaveBeenCalledWith('Удалить этот запуск и его результаты?')
    expect(onDelete).toHaveBeenCalledWith(1)
  })
})
