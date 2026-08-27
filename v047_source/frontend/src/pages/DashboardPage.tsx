import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, CheckCircle2, CircleX, Inbox, ListTodo, ShieldAlert, Users } from 'lucide-react'
import { api } from '../api/client'
import { MetricCard } from '../components/MetricCard'
import { Card, PageHeader, Skeleton, Status } from '../components/ui'
import type { Dashboard } from '../types'
import { formatLocalTime } from '../utils/time'

const stateLabels: Record<string, string> = {
  empty: 'Список пуст', draft: 'Готово к запуску', running: 'Работает', paused: 'Пауза',
  stopped: 'Остановлено', completed: 'Работа завершена', limit_reached: 'Лимит достигнут',
  waiting_limit: 'Ожидание суточного лимита', needs_attention: 'Есть группа для безопасной сверки', requires_login: 'Нужен вход в VK',
}

export default function DashboardPage() {
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: () => api<Dashboard>('/dashboard'), refetchInterval: 2500 })
  const data = dashboard.data
  const cards = data ? [
    ['Активных аккаунтов', data.metrics.active_accounts, Users, 'blue'], ['Осталось групп', data.metrics.remaining, ListTodo, 'violet'],
    ['Сейчас обрабатывается', data.metrics.processing, Activity, 'amber'], ['Успешно написали', data.metrics.success, CheckCircle2, 'green'],
    ['Не удалось написать', data.metrics.failed, CircleX, 'red'], ['Непрочитанных диалогов', data.metrics.unread, Inbox, 'cyan'],
  ] as const : []

  return <div className="page"><PageHeader title="Главная" description="Вся работа аккаунтов и групп — в одном месте" />
    <div className="state-banner"><div><span>Текущее состояние</span><strong>{data ? stateLabels[data.work_state] || data.work_state : 'Загрузка…'}</strong></div>{data && <Status state={data.work_state}>{stateLabels[data.work_state] || data.work_state}</Status>}</div>
    {data?.work_state === 'waiting_limit' && <div className="quota-wait-banner"><ShieldAlert size={20} /><div><strong>Ожидание суточного лимита</strong><span>Отправка не возобновится сама после перезапуска приложения. Когда лимит станет доступен, явно нажмите «Продолжить».</span></div></div>}
    <div className="metrics-grid">{dashboard.isLoading ? Array.from({ length: 6 }, (_, index) => <Card key={index}><Skeleton height={82} /></Card>) : cards.map(([label, value, Icon, color]) => <MetricCard key={label} label={label} value={value} icon={Icon} color={color} />)}</div>
    <div className="dashboard-grid dashboard-grid--single"><Card><div className="card-heading"><div><h2>Последние события</h2><p>Понятная история действий приложения</p></div><Activity size={19} /></div><div className="event-list">{data?.events.length ? data.events.map(event => <div className="event-row" key={event.id}><time>{formatLocalTime(event.time)}</time><i className={`event-dot event-dot--${event.level}`} /><span>{event.message}</span></div>) : <div className="soft-empty">Событий пока нет.</div>}</div></Card></div>
  </div>
}
