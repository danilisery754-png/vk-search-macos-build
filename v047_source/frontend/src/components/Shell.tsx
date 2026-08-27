import {
  CheckCircle2, CircleX, ClipboardList, FileClock, Inbox, LayoutDashboard,
  Menu, Search, Settings, Users, X,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type CSSProperties, type DragEvent, type FormEvent, type PropsWithChildren } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { Dashboard } from '../types'
import { Status } from './ui'
import WorkControls from './WorkControls'

const defaultOrder = ['/', '/accounts', '/groups', '/inbox', '/success', '/failed', '/logs']
const navigation = {
  '/': { icon: LayoutDashboard, label: 'Главная' },
  '/accounts': { icon: Users, label: 'Аккаунты' },
  '/groups': { icon: ClipboardList, label: 'Список групп' },
  '/inbox': { icon: Inbox, label: 'Сообщения' },
  '/success': { icon: CheckCircle2, label: 'Успешно написали' },
  '/failed': { icon: CircleX, label: 'Не удалось написать' },
  '/logs': { icon: FileClock, label: 'Логи' },
} as const
type NavRoute = keyof typeof navigation

function normalizeOrder(value: unknown): NavRoute[] {
  const known = new Set(defaultOrder)
  const candidate = Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && known.has(item)) : []
  const unique = [...new Set(candidate)]
  return [...unique, ...defaultOrder.filter(item => !unique.includes(item))] as NavRoute[]
}

function workScaleDimensions(scale: number): CSSProperties {
  const compensated = scale < 1 ? `${100 / scale}%` : '100%'
  return {
    '--work-scale': String(scale),
    zoom: scale,
    width: compensated,
    height: compensated,
    minWidth: compensated,
    minHeight: compensated,
  } as CSSProperties
}

export default function Shell({ children }: PropsWithChildren) {
  const [open, setOpen] = useState(true)
  const [search, setSearch] = useState('')
  const [order, setOrder] = useState<NavRoute[]>(defaultOrder as NavRoute[])
  const [dragging, setDragging] = useState<NavRoute | null>(null)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const dashboard = useQuery({ queryKey: ['dashboard-shell'], queryFn: () => api<Dashboard>('/dashboard'), refetchInterval: 2500 })
  const settings = useQuery({ queryKey: ['settings-shell'], queryFn: () => api<Record<string, unknown>>('/settings') })
  const saveOrder = useMutation({ mutationFn: (navigation_order: NavRoute[]) => api('/settings', { method: 'PATCH', body: JSON.stringify({ values: { navigation_order } }) }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings-shell'] }) })
  useEffect(() => { if (settings.data) setOrder(normalizeOrder(settings.data.navigation_order)) }, [settings.data])
  const rawScale = Number(settings.data?.ui_scale ?? 1)
  const workScale = Math.min(3, Math.max(.75, Number.isFinite(rawScale) ? rawScale : 1))
  const workScaleStyle = workScaleDimensions(workScale)
  const navItems = useMemo(() => order.map(to => ({ to, ...navigation[to] })), [order])
  const submitSearch = (event: FormEvent) => { event.preventDefault(); navigate(`/groups${search.trim() ? `?q=${encodeURIComponent(search.trim())}` : ''}`) }
  const drop = (event: DragEvent, target: NavRoute) => {
    event.preventDefault(); if (!dragging || dragging === target) return setDragging(null)
    const next = [...order]; const sourceIndex = next.indexOf(dragging); const targetIndex = next.indexOf(target)
    next.splice(sourceIndex, 1); next.splice(targetIndex, 0, dragging); setOrder(next); setDragging(null); saveOrder.mutate(next)
  }
  const state = dashboard.data?.work_state || 'empty'
  const stateLabel = state === 'running' ? 'Работает' : state === 'paused' ? 'Пауза' : state === 'waiting_limit' ? 'Ожидание лимита' : state === 'requires_login' ? 'Нужен вход' : state === 'needs_attention' ? 'Есть группа для сверки' : 'Остановлено'

  return <div className={`app-shell ${open ? '' : 'app-shell--collapsed'}`}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark" role="img" aria-label="VK Search" /><div className="brand-copy"><strong>VK Search</strong><span>Community</span></div></div>
      <nav>{navItems.map(({ to, icon: Icon, label }) => <NavLink key={to} to={to} end={to === '/'} title={`${label} · перетащите для изменения порядка`} draggable onDragStart={() => setDragging(to)} onDragEnd={() => setDragging(null)} onDragOver={event => event.preventDefault()} onDrop={event => drop(event, to)} className={dragging === to ? 'nav-dragging' : undefined}><Icon size={20} /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-bottom"><NavLink to="/settings"><Settings size={20} /><span>Настройки</span></NavLink><div className="local-label"><i />Данные только на этом ПК</div></div>
    </aside>
    <div className="workspace">
      <div className="window-bar"><button className="icon-button" onClick={() => setOpen(value => !value)} aria-label="Меню">{open ? <X size={18} /> : <Menu size={18} />}</button><form className="global-search" onSubmit={submitSearch}><Search size={15} /><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Группа, ссылка или аккаунт" /></form><WorkControls state={state} /><div className="window-indicators"><Status state={state}>{stateLabel}</Status><button onClick={() => navigate('/inbox?filter=unread')} title="Непрочитанные диалоги"><Inbox size={16} /><b>{dashboard.data?.metrics.unread || 0}</b></button><button onClick={() => navigate('/settings')} title="Настройки"><Settings size={17} /></button></div></div>
      <main><div className="work-scale-root" data-testid="work-scale-root" style={workScaleStyle}>{children}</div></main>
    </div>
  </div>
}
