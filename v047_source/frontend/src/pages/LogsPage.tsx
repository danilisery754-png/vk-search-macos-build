import { useQuery } from '@tanstack/react-query'
import { ChevronDown, Copy, FileClock, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { api } from '../api/client'
import { Card, EmptyState, PageHeader } from '../components/ui'
import { formatLocalDateTime } from '../utils/time'

interface LogEntry {
  id: number; created_at: string; level: string; category?: string; event_type?: string
  account_id: number | null; work_item_id: number | null; account_display_name?: string | null; message: string; technical: Record<string, unknown>
}

const categoryLabels: Record<string, string> = { outreach: 'Рассылка', messages: 'Сообщения', auth: 'Авторизация', system: 'Система', all: 'Все' }

function routeTone(value: unknown) {
  const state = String(value || '')
  return state === 'sent' ? 'ok' : state === 'failed_final' ? 'bad' : ['temporary_error','unknown','sending'].includes(state) ? 'warn' : 'idle'
}

export default function LogsPage() {
  const [search, setSearch] = useState('')
  const [level, setLevel] = useState('all')
  const [category, setCategory] = useState('outreach')
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const query = new URLSearchParams({ limit: '1000', ...(category !== 'all' ? { category } : {}), ...(level !== 'all' ? { level } : {}) }).toString()
  const logs = useQuery({ queryKey: ['logs', category, level], queryFn: () => api<LogEntry[]>(`/logs?${query}`), refetchInterval: 3000 })
  const rows = useMemo(() => (logs.data || []).filter(row => row.message.toLowerCase().includes(search.toLowerCase())), [logs.data, search])

  return <div className="page"><PageHeader title="Логи" description="Рассылка по умолчанию; системные события остаются доступными отдельным фильтром" /><Card className="table-card">
    <div className="table-toolbar"><label className="search-box"><Search size={17} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Поиск по событиям" /></label><select value={category} onChange={e => setCategory(e.target.value)}>{['outreach','messages','auth','system','all'].map(value => <option key={value} value={value}>{categoryLabels[value]}</option>)}</select><select value={level} onChange={e => setLevel(e.target.value)}><option value="all">Все уровни</option><option value="info">Обычные</option><option value="warning">Предупреждения</option><option value="error">Ошибки</option></select></div>
    {!rows.length ? <EmptyState icon={<FileClock />} title="Событий пока нет" text={category === 'outreach' ? 'Здесь появится понятная история отправок по группам.' : 'Для выбранного фильтра событий нет.'} /> : <div className="log-list">{rows.map(row => {
      const tech = row.technical || {}; const hasTechnical = Object.keys(tech).length > 0; const open = expanded.has(row.id); const outreach = row.category === 'outreach' && row.event_type === 'outreach_result'
      return <article key={row.id} className={`log-entry log-row--${row.level} ${outreach ? 'outreach-log' : ''}`}>
        {outreach ? <div className="outreach-log-row"><time>{formatLocalDateTime(row.created_at)}</time><img src={String(tech.account_avatar_url || '')} alt="" onError={event => { event.currentTarget.style.visibility = 'hidden' }} /><div className="outreach-main"><strong>{String(row.account_display_name || tech.account_name || `Аккаунт #${row.account_id || ''}`)}</strong><span>{String(tech.outcome) === 'success' ? ' написал ' : ' не удалось написать '}<a href={String(tech.community_url || '#')} target="_blank" rel="noreferrer">{String(tech.community_name || tech.community_url || 'сообщество')}</a><button aria-label="Скопировать ссылку" onClick={() => navigator.clipboard?.writeText(String(tech.community_url || ''))}><Copy size={12} /></button></span></div><div className={`route-chip route-chip--${routeTone(tech.message_state)}`}>ЛС</div><div className={`route-chip route-chip--${routeTone(tech.suggested_state)}`}>Предложка</div>{hasTechnical && <button className="log-expand" onClick={() => setExpanded(previous => { const next = new Set(previous); next.has(row.id) ? next.delete(row.id) : next.add(row.id); return next })}><ChevronDown size={15} className={open ? 'rotate' : ''} /></button>}</div> : <button className="log-row" onClick={() => hasTechnical && setExpanded(previous => { const next = new Set(previous); next.has(row.id) ? next.delete(row.id) : next.add(row.id); return next })}><time>{formatLocalDateTime(row.created_at)}</time><i /><div><p>{row.message}</p>{(row.account_id || row.work_item_id) && <small>{row.account_id && `Аккаунт #${row.account_id}`} {row.work_item_id && `Группа в работе #${row.work_item_id}`}</small>}</div>{hasTechnical && <ChevronDown size={15} className={open ? 'rotate' : ''} />}</button>}
        {open && <pre className="technical-details">{JSON.stringify(tech, null, 2)}</pre>}
      </article>
    })}</div>}
  </Card></div>
}
