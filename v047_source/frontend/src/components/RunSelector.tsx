import { CalendarClock, Check, ChevronDown, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { RunSummary } from '../types'
import { formatLocalDateTime } from '../utils/time'
import ScaledOverlay from './ScaledOverlay'

const stateLabels: Record<string, string> = {
  draft: 'Черновик', running: 'Выполняется', paused: 'Приостановлен', stopped: 'Остановлен',
  completed: 'Завершён', limit_reached: 'Достигнут лимит', needs_attention: 'Нужно внимание', failed: 'Ошибка',
}

function formatDate(value: string | null) {
  return value ? formatLocalDateTime(value) : 'без даты'
}

export default function RunSelector({
  runs,
  currentRunId,
  selectedRunId,
  onSelect,
  onDelete,
}: {
  runs: RunSummary[]
  currentRunId: number | null
  selectedRunId: number | null
  onSelect: (id: number) => void
  onDelete: (id: number) => void
}) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const selected = runs.find(run => run.id === selectedRunId) || null
  const archived = selectedRunId != null && currentRunId != null && selectedRunId !== currentRunId

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => { document.removeEventListener('pointerdown', onPointerDown); document.removeEventListener('keydown', onKeyDown) }
  }, [open])

  return <div className="run-selector-wrap">
    <div className="run-selector" ref={rootRef}>
      <button ref={triggerRef} className="run-selector-trigger" type="button" aria-expanded={open} onClick={() => setOpen(value => !value)}><CalendarClock size={15} /><span>Запуски{selected ? ` · #${selected.id}` : ''}</span><ChevronDown size={14} /></button>
      {open && <ScaledOverlay anchor={triggerRef.current} placement="bottom-start"><div className="run-selector-panel" role="menu">
        <div className="run-selector-title"><strong>История запусков</strong><span>Хранится бессрочно</span></div>
        <div className="run-selector-list">
          {runs.length ? runs.map(run => <div className={`run-selector-row ${run.id === selectedRunId ? 'active' : ''}`} key={run.id}>
            <button type="button" role="menuitem" aria-label={`Запуск #${run.id} · ${formatDate(run.started_at)}`} onClick={() => { onSelect(run.id); setOpen(false) }}>
              <span className="run-select-check">{run.id === selectedRunId ? <Check size={13} /> : null}</span>
              <span><strong>#{run.id} · {formatDate(run.started_at)}</strong><small>{run.original_count} групп · {stateLabels[run.state] || run.state} · ✓ {run.success_count} / × {run.failure_count}</small></span>
            </button>
            {run.id !== currentRunId && <button className="run-delete" type="button" aria-label={`Удалить запуск #${run.id}`} title="Удалить запуск" onClick={() => { if (confirm('Удалить этот запуск и его результаты?')) onDelete(run.id) }}><Trash2 size={14} /></button>}
          </div>) : <div className="run-selector-empty">Запусков пока нет</div>}
        </div>
      </div></ScaledOverlay>}
    </div>
    {archived && selected && <div className="run-archive-banner"><span>Просмотр архива: запуск #{selected.id} · {formatDate(selected.started_at)}</span><button type="button" onClick={() => currentRunId != null && onSelect(currentRunId)}>Вернуться к текущему запуску</button></div>}
  </div>
}
