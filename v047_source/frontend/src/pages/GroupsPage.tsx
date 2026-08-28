import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ClipboardPaste, Link2, Search, Trash2, UploadCloud } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { api } from '../api/client'
import { useSessionUiStore } from '../components/SessionUiStore'
import { Button, Card, EmptyState, PageHeader, Status } from '../components/ui'
import type { WorkItem } from '../types'

const stateLabel: Record<string, string> = { waiting: 'Ожидает', assigned: 'Назначена', processing: 'Обрабатывается', retry_wait: 'Ожидает повтор', reconcile_required: 'Нужна проверка', paused: 'Приостановлена' }
type ImportMode = 'append' | 'replace_waiting'
interface ImportResult { found: number; added: number; duplicates: number; unresolved: string[]; replaced?: number; cancelled?: boolean }
interface GroupsSessionUi {
  selectedIds: number[]
  search: string
  status: string
  sort: 'group_name' | 'account' | 'state'
}

const GROUPS_SESSION_KEY = 'groups'

export default function GroupsPage() {
  const client = useQueryClient()
  const uiStore = useSessionUiStore()
  const [params] = useSearchParams()
  const remembered = uiStore.read<GroupsSessionUi>(GROUPS_SESSION_KEY)
  const explicitSearch = params.get('q')
  const [text, setText] = useState('')
  const [confirmReplace, setConfirmReplace] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(() => new Set(remembered?.selectedIds || []))
  const [search, setSearch] = useState(explicitSearch ?? remembered?.search ?? '')
  const [status, setStatus] = useState(remembered?.status || 'all')
  const [sort, setSort] = useState<'group_name' | 'account' | 'state'>(remembered?.sort || 'group_name')

  useEffect(() => {
    if (params.has('q')) setSearch(params.get('q') || '')
  }, [params])

  const groups = useQuery({ queryKey: ['groups'], queryFn: () => api<{ total: number; items: WorkItem[] }>('/groups'), refetchInterval: 3000 })

  useEffect(() => {
    if (!groups.data) return
    const existing = new Set(groups.data.items.map(item => item.id))
    setSelected(previous => {
      const next = new Set([...previous].filter(id => existing.has(id)))
      if (next.size === previous.size && [...next].every(id => previous.has(id))) return previous
      return next
    })
  }, [groups.data])

  useEffect(() => {
    uiStore.write<GroupsSessionUi>(GROUPS_SESSION_KEY, {
      selectedIds: [...selected],
      search,
      status,
      sort,
    })
  }, [uiStore, selected, search, status, sort])

  const importMutation = useMutation({
    mutationFn: (mode: ImportMode) => api<ImportResult>('/groups/import', { method: 'POST', body: JSON.stringify({ text, mode }) }),
    onSuccess: result => {
      const replaced = Number(result.replaced || 0)
      toast.success(replaced ? `Заменено ожидающих: ${replaced}. Добавлено: ${result.added}` : `Добавлено групп: ${result.added}`)
      if (result.unresolved.length) toast.warning(`Не удалось определить: ${result.unresolved.length}`)
      setText('')
      setConfirmReplace(false)
      client.invalidateQueries({ queryKey: ['groups'] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const remove = useMutation({
    mutationFn: () => api<{ removed: number }>('/groups/remove', { method: 'POST', body: JSON.stringify({ ids: [...selected] }) }),
    onSuccess: result => {
      if (result.removed) toast.success(`Удалено: ${result.removed}`)
      else toast.warning('Выбранные элементы сейчас нельзя удалить')
      setSelected(new Set())
      client.invalidateQueries({ queryKey: ['groups'] })
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const removeSelected = () => {
    if (!selected.size) return
    if (!confirm('Удалить выбранные элементы из активного рабочего списка? Элемент со статусом «Нужна проверка» будет удалён окончательно и не будет повторно отправляться.')) return
    remove.mutate()
  }
  const items = useMemo(() => (groups.data?.items || [])
    .filter(item => (status === 'all' || item.state === status) && `${item.id} ${item.group_name} ${item.url} ${item.account} ${item.state} ${item.last_error}`.toLowerCase().includes(search.toLowerCase()))
    .sort((left, right) => String(left[sort]).localeCompare(String(right[sort]), 'ru-RU')), [groups.data, search, status, sort])

  return <div className="page">
    <PageHeader title="Список групп" description="Одна постоянная очередь: аккаунты берут из неё следующие группы по мере доступной суточной квоты" />
    <Card className="import-card"><div className="import-copy"><div className="import-icon"><UploadCloud /></div><div><h2>Добавить группы</h2><p>Вставляйте ссылки, ID, текст из Excel или несколько ссылок в одной строке — приложение всё очистит само.</p></div></div>
      <textarea value={text} onChange={event => { setText(event.target.value); setConfirmReplace(false) }} placeholder={'https://vk.com/example\nvk.ru/public123456\nclub777'} />
      <div className="import-footer"><span><ClipboardPaste size={15} />Найду ссылки даже среди лишнего текста</span><div className="import-actions"><Button disabled={!text.trim()} loading={importMutation.isPending} onClick={() => importMutation.mutate('append')}><Link2 size={17} />Добавить в список</Button><Button variant="secondary" disabled={!text.trim() || importMutation.isPending} onClick={() => setConfirmReplace(true)}>Заменить ожидающий список</Button></div></div>
      {confirmReplace && <div className="replace-confirm"><div><strong>Заменить только ещё не начатую часть очереди?</strong><span>Уже начатые группы сохранятся: обрабатываемые, завершённые и требующие проверки элементы не удаляются.</span></div><div><Button variant="danger" loading={importMutation.isPending} onClick={() => importMutation.mutate('replace_waiting')}>Подтвердить замену</Button><Button variant="secondary" onClick={() => setConfirmReplace(false)}>Отмена</Button></div></div>}
    </Card>
    <Card className="table-card"><div className="table-toolbar"><div><h2>Активный рабочий список</h2><span>{groups.data?.total || 0} групп</span></div><div className="toolbar-actions">
      <label className="search-box"><Search size={17} /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Найти группу или аккаунт" /></label>
      <select value={status} onChange={e => setStatus(e.target.value)}><option value="all">Все статусы</option>{Object.entries(stateLabel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
      <select value={sort} onChange={e => setSort(e.target.value as typeof sort)}><option value="group_name">По группе</option><option value="account">По аккаунту</option><option value="state">По статусу</option></select>
      <span className="selection-counter">Выбрано: {selected.size}</span><Button variant="danger" disabled={!selected.size || remove.isPending} loading={remove.isPending} onClick={removeSelected}><Trash2 size={16} />Удалить выбранное</Button>
    </div></div>
      {!items.length ? <EmptyState icon={<Link2 />} title="Список пока пуст" text="Вставьте группы выше — они появятся здесь после очистки и проверки." /> : <div className="data-table-wrap"><table className="data-table"><thead><tr><th><input type="checkbox" checked={selected.size === items.length && !!items.length} onChange={e => setSelected(e.target.checked ? new Set(items.map(x => x.id)) : new Set())} /></th><th>Группа</th><th>Ссылка</th><th>Статус</th><th>Аккаунт</th><th>Попыток</th></tr></thead>
        <tbody>{items.map(item => <tr key={item.id}><td><input type="checkbox" checked={selected.has(item.id)} onChange={e => setSelected(previous => { const next = new Set(previous); e.target.checked ? next.add(item.id) : next.delete(item.id); return next })} /></td><td><strong>{item.group_name}</strong>{item.last_error && <small className="error-hint">{item.last_error}</small>}</td><td><a href={item.url} target="_blank">{item.url}</a></td><td><Status state={item.state}>{stateLabel[item.state] || item.state}</Status></td><td>{item.account}</td><td>{item.attempts}</td></tr>)}</tbody></table></div>}
    </Card>
  </div>
}
