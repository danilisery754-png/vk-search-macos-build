import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { CheckCircle2, CircleX, Clipboard, Download, ExternalLink, Link2, Search, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { toast } from 'sonner'
import { api, downloadExport } from '../api/client'
import RunSelector from '../components/RunSelector'
import { Button, Card, EmptyState, PageHeader } from '../components/ui'
import { useResultRunSelection } from '../hooks/useResultRunSelection'
import type { ResultItem, RunHistoryPayload, WorkHistory } from '../types'
import { formatLocalDateTime } from '../utils/time'

export default function ResultsPage({ kind }: { kind: 'success' | 'failed' }) {
  const success = kind === 'success'
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [mode, setMode] = useState<'table' | 'links'>('table')
  const [sort, setSort] = useState<'completed_at' | 'group_name' | 'account'>('completed_at')
  const [ascending, setAscending] = useState(false)
  const [historyId, setHistoryId] = useState<number | null>(null)
  const [columnWidths, setColumnWidths] = useState([38, 300, 120, 120, 210, 145, 150])

  const runs = useQuery({
    queryKey: ['runs'],
    queryFn: () => api<RunHistoryPayload>('/runs'),
    refetchInterval: 4000,
  })
  const runIds = useMemo(() => runs.data?.items.map(run => run.id) || [], [runs.data?.items])
  const { selectedRunId, selectRun, returnToCurrent } = useResultRunSelection(runs.data?.current_run_id ?? null, runIds, runs.data != null)
  const query = useQuery({
    queryKey: ['results', kind, selectedRunId, search],
    queryFn: () => api<{ total: number; items: ResultItem[] }>(`/results/${kind}?run_id=${selectedRunId}&search=${encodeURIComponent(search)}&limit=2000`),
    enabled: selectedRunId != null,
    refetchInterval: selectedRunId != null && selectedRunId === runs.data?.current_run_id ? 4000 : false,
  })
  const history = useQuery({ queryKey: ['work-history', historyId], queryFn: () => api<WorkHistory>(`/groups/${historyId}/history`), enabled: !!historyId })
  const removeRun = useMutation({
    mutationFn: (runId: number) => api<{ ok: boolean }>(`/runs/${runId}`, { method: 'DELETE' }),
    onSuccess: (_result, deletedRunId) => {
      if (deletedRunId === selectedRunId) returnToCurrent()
      client.invalidateQueries({ queryKey: ['runs'] })
      client.invalidateQueries({ queryKey: ['results', 'success'] })
      client.invalidateQueries({ queryKey: ['results', 'failed'] })
      toast.success(`Запуск #${deletedRunId} удалён`)
    },
    onError: (error: Error) => toast.error(error.message || 'Не удалось удалить запуск'),
  })

  useEffect(() => { setSelected(new Set()) }, [selectedRunId, kind])

  const items = useMemo(() => [...(query.data?.items || [])].sort((left, right) => {
    const a = String(left[sort] || '').toLocaleLowerCase('ru-RU')
    const b = String(right[sort] || '').toLocaleLowerCase('ru-RU')
    return (a.localeCompare(b, 'ru-RU') || left.id - right.id) * (ascending ? 1 : -1)
  }), [query.data, sort, ascending])
  const parentRef = useRef<HTMLDivElement>(null)
  const virtual = useVirtualizer({ count: items.length, getScrollElement: () => parentRef.current, estimateSize: () => 57, overscan: 10 })
  const selectedRows = useMemo(() => items.filter(item => selected.has(item.id)), [items, selected])
  const gridColumns = columnWidths.map(value => `${value}px`).join(' ')

  function beginResize(index: number, event: ReactMouseEvent) {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = columnWidths[index]
    const move = (next: MouseEvent) => setColumnWidths(previous => previous.map((width, current) => current === index ? Math.max(current === 0 ? 32 : 80, startWidth + next.clientX - startX) : width))
    const stop = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', stop) }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', stop)
  }

  async function copyLinks(rows: ResultItem[]) {
    await navigator.clipboard.writeText(rows.map(item => item.url).join('\n'))
    toast.success(`Скопировано ссылок: ${rows.length}`)
  }
  async function copyTable(rows: ResultItem[]) {
    const header = ['Группа', 'Ссылка', 'ЛС', 'Предложка', 'Куда получилось', 'Аккаунт', 'Время'].join('\t')
    const lines = rows.map(item => [item.group_name, item.url, item.message_state === 'sent' ? 'Отправлено' : 'Не отправлено', item.suggested_state === 'sent' ? 'Отправлено' : 'Не отправлено', item.destination, item.account, item.completed_at || ''].join('\t'))
    await navigator.clipboard.writeText([header, ...lines].join('\n'))
    toast.success(`Скопировано строк: ${rows.length}`)
  }
  const allSelected = !!items.length && selected.size === items.length
  const exportSelection = selected.size ? [...selected] : undefined
  const currentRunId = runs.data?.current_run_id ?? null

  return <div className="page page--results">
    <PageHeader title={success ? 'Успешно написали' : 'Не удалось написать'} description={success ? 'Группы, где хотя бы один способ связи сработал' : 'Группы, где оба способа подтверждённо не сработали'} actions={<div className="segmented"><button className={mode === 'table' ? 'active' : ''} onClick={() => setMode('table')}>Таблица</button><button className={mode === 'links' ? 'active' : ''} onClick={() => setMode('links')}>Только ссылки</button></div>} />
    <RunSelector runs={runs.data?.items || []} currentRunId={currentRunId} selectedRunId={selectedRunId} onSelect={selectRun} onDelete={id => removeRun.mutate(id)} />
    <div className={`result-summary ${success ? 'result-summary--success' : 'result-summary--failed'}`}><div className="result-big-icon">{success ? <CheckCircle2 /> : <CircleX />}</div><div><span>Всего в разделе</span><strong>{query.data?.total || 0}</strong></div><p>{success ? 'Можно скопировать отдельный чистый список ссылок одним нажатием.' : 'Причины ЛС и предложки сохранены отдельно для каждой группы.'}</p></div>
    <Card className="table-card"><div className="table-toolbar"><label className="search-box"><Search size={17} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Поиск по группе, ссылке или аккаунту" /></label><div className="toolbar-actions"><select value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="completed_at">По времени</option><option value="group_name">По группе</option><option value="account">По аккаунту</option></select><Button variant="ghost" onClick={() => setAscending(value => !value)}>{ascending ? 'А–Я' : 'Я–А'}</Button>
      <Button variant="secondary" onClick={() => copyTable(selected.size ? selectedRows : items)}><Clipboard size={16} />{selected.size ? 'Копировать выбранное' : 'Копировать таблицу'}</Button>
      <Button variant="secondary" onClick={() => copyLinks(selected.size ? selectedRows : items)}><Link2 size={16} />{selected.size ? 'Выбранные ссылки' : 'Все ссылки'}</Button>
      <Button variant="secondary" disabled={selectedRunId == null} onClick={() => selectedRunId != null && downloadExport(kind, 'links', exportSelection, selectedRunId)}><Download size={16} />TXT</Button>
      <Button variant="secondary" disabled={selectedRunId == null} onClick={() => selectedRunId != null && downloadExport(kind, 'csv', exportSelection, selectedRunId)}><Download size={16} />Экспорт CSV</Button>
      <Button variant="secondary" disabled={selectedRunId == null} onClick={() => selectedRunId != null && downloadExport(kind, 'xlsx', exportSelection, selectedRunId)}><Download size={16} />XLSX</Button>
    </div></div>
      {!items.length ? <EmptyState icon={success ? <CheckCircle2 /> : <CircleX />} title="Здесь пока пусто" text={selectedRunId == null ? 'Сначала создайте запуск — его результаты будут храниться отдельно.' : 'Для выбранного запуска в этом разделе пока нет результатов.'} /> : mode === 'links' ? <div className="links-mode"><div className="links-mode-head"><span>{items.length} ссылок</span><Button onClick={() => copyLinks(items)}><Clipboard size={16} />Скопировать всё</Button></div>{items.map(item => <a key={item.id} href={item.url} target="_blank">{item.url}<ExternalLink size={14} /></a>)}</div> : <>
        <div className="virtual-header result-grid" style={{ gridTemplateColumns: gridColumns }}><div><input type="checkbox" checked={allSelected} onChange={e => setSelected(e.target.checked ? new Set(items.map(x => x.id)) : new Set())} /></div>{['Группа', 'ЛС', 'Предложка', success ? 'Куда получилось' : 'Причина', 'Аккаунт', 'Время'].map((label, headerIndex) => <div className="resizable-head" key={label}>{label}<i onMouseDown={event => beginResize(headerIndex + 1, event)} /></div>)}</div>
        <div className="virtual-body" ref={parentRef}><div style={{ height: `${virtual.getTotalSize()}px`, position: 'relative', minWidth: `${columnWidths.reduce((sum, value) => sum + value, 0) + 100}px` }}>{virtual.getVirtualItems().map(row => { const item = items[row.index]; const reason = [item.message_reason, item.suggested_reason].filter(Boolean).join('; '); return <div className="virtual-row result-grid" key={item.id} style={{ height: `${row.size}px`, transform: `translateY(${row.start}px)`, gridTemplateColumns: gridColumns }}>
          <div><input type="checkbox" checked={selected.has(item.id)} onChange={e => setSelected(previous => { const next = new Set(previous); e.target.checked ? next.add(item.id) : next.delete(item.id); return next })} /></div><div><button className="link-button" onClick={() => setHistoryId(item.work_item_id)}>{item.group_name}</button><a href={item.url} target="_blank">{item.url}</a></div><div className={item.message_state === 'sent' ? 'yes' : 'no'}>{item.message_state === 'sent' ? '✓ Отправлено' : '× Не отправлено'}</div><div className={item.suggested_state === 'sent' ? 'yes' : 'no'}>{item.suggested_state === 'sent' ? '✓ Отправлено' : '× Не отправлено'}</div><div title={reason}>{success ? item.destination : reason || 'Неизвестная причина'}</div><div>{item.account}</div><div>{item.completed_at ? formatLocalDateTime(item.completed_at) : '—'}</div>
        </div> })}</div></div></>}
    </Card>
    {historyId && <div className="drawer-backdrop" onMouseDown={() => setHistoryId(null)}><aside className="history-drawer" onMouseDown={event => event.stopPropagation()}><header><div><span>История обработки</span><h2>{history.data?.group_name || 'Загрузка…'}</h2></div><button className="icon-button" onClick={() => setHistoryId(null)}><X size={18} /></button></header>{history.data && <div className="history-content"><a href={history.data.url} target="_blank">{history.data.url}</a><div className="history-summary"><span>Аккаунт <b>{history.data.account || '—'}</b></span><span>Попыток <b>{history.data.attempts_count}</b></span><span>Итог <b>{history.data.result?.destination || history.data.state}</b></span></div><h3>ЛС сообщества</h3><p>{history.data.result?.message_reason || history.data.result?.message_state || 'Не выполнялось'}</p><h3>Предложенная запись</h3><p>{history.data.result?.suggested_reason || history.data.result?.suggested_state || 'Не выполнялось'}</p><h3>Попытки и события</h3>{history.data.attempts.map(attempt => <article key={attempt.id}><time>{formatLocalDateTime(attempt.created_at)}</time><strong>{attempt.direction === 'message' ? 'ЛС' : 'Предложка'} · {attempt.state}</strong><p>{attempt.reason || `VK object ID: ${attempt.vk_object_id || '—'}`}</p></article>)}{history.data.events.map(event => <article key={`event-${event.id}`}><time>{formatLocalDateTime(event.created_at)}</time><strong>{event.message}</strong>{Object.keys(event.technical).length > 0 && <pre>{JSON.stringify(event.technical, null, 2)}</pre>}</article>)}</div>}</aside></div>}
  </div>
}
