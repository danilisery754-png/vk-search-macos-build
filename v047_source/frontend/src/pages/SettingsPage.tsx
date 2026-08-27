import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DatabaseBackup, HelpCircle, MessageSquareText, Save, Timer, Wrench } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api/client'
import { MessageVariantsEditor } from '../components/MessageVariantsEditor'
import { SettingsTabs, type SettingsSection } from '../components/SettingsTabs'
import { Button, Card, PageHeader } from '../components/ui'
import { formatLocalDateTime } from '../utils/time'

type SettingValue = string | number | boolean | string[]
type Settings = Record<string, SettingValue>
interface BackupRow { name: string; size: number; created_at: string }

function scrollSettingsToTop() {
  const content = document.querySelector<HTMLElement>('.settings-content--bounded')
  if (content) content.scrollTop = 0
}

function scalePercent(value: unknown): number {
  const scale = Number(value ?? 1)
  const safe = Number.isFinite(scale) ? scale : 1
  return Math.round(Math.min(3, Math.max(.75, safe)) * 100)
}

export default function SettingsPage() {
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['settings'], queryFn: () => api<Settings>('/settings') })
  const backups = useQuery({ queryKey: ['backups'], queryFn: () => api<BackupRow[]>('/backups') })
  const [values, setValues] = useState<Settings>({})
  const [activeSection, setActiveSection] = useState<SettingsSection>('sending')
  const [draftUiScalePercent, setDraftUiScalePercent] = useState(100)
  useEffect(() => {
    if (!query.data) return
    setValues(query.data)
    setDraftUiScalePercent(scalePercent(query.data.ui_scale))
  }, [query.data])
  useEffect(() => {
    scrollSettingsToTop()
    if (window.location.hash) window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
  }, [])
  const save = useMutation({ mutationFn: () => api<Settings>('/settings', { method: 'PATCH', body: JSON.stringify({ values }) }), onSuccess: data => { setValues(data); toast.success('Настройки сохранены'); client.setQueryData(['settings'], data) }, onError: (error: Error) => toast.error(error.message) })
  const saveUiScale = useMutation({
    mutationFn: () => {
      const ui_scale = Math.min(3, Math.max(.75, draftUiScalePercent / 100))
      return api<Settings>('/settings', { method: 'PATCH', body: JSON.stringify({ values: { ui_scale } }) })
    },
    onSuccess: data => {
      setValues(data)
      setDraftUiScalePercent(scalePercent(data.ui_scale))
      client.setQueryData(['settings'], data)
      client.setQueryData(['settings-shell'], data)
      toast.success('Масштаб сохранён')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const createBackup = useMutation({ mutationFn: () => api<{ name: string }>('/backups', { method: 'POST' }), onSuccess: result => { toast.success(`Резервная копия создана: ${result.name}`); client.invalidateQueries({ queryKey: ['backups'] }) }, onError: (error: Error) => toast.error(error.message) })
  const set = (key: string, value: SettingValue) => setValues(previous => ({ ...previous, [key]: value }))
  const list = (key: string, legacyKey: string) => Array.isArray(values[key]) ? values[key] as string[] : [String(values[legacyKey] || '')]
  const selectSection = (section: SettingsSection) => { setActiveSection(section); scrollSettingsToTop() }
  const savedUiScalePercent = scalePercent(values.ui_scale)

  return <div className="page"><PageHeader title="Настройки" description="Постоянные параметры работы — не нужно задавать их при каждом запуске" actions={<Button loading={save.isPending} onClick={() => save.mutate()}><Save size={17} />Сохранить изменения</Button>} />
    <div className="settings-layout"><SettingsTabs active={activeSection} onSelect={selectSection} /><div className="settings-content settings-content--bounded">
      {activeSection === 'sending' && <Card className="settings-card" role="tabpanel"><div className="settings-section-head"><div className="settings-icon"><Timer /></div><div><h2>Рассылка</h2><p>Обращения, лимиты, задержки и поведение повторов</p></div></div>
        <div className="settings-grid"><label className="field"><span>Суточный лимит на аккаунт <span title="У каждого активного аккаунта собственное скользящее 24-часовое окно"><HelpCircle size={14} /></span></span><input type="number" min="1" value={Number(values.max_groups_per_account || 50)} onChange={event => set('max_groups_per_account', Number(event.target.value))} /><small>Лимит действует отдельно для каждого аккаунта в течение 24 часов с первой учтённой группы.</small></label><label className="field"><span>Режим задержки</span><select value={String(values.delay_mode || 'fixed')} onChange={event => set('delay_mode', event.target.value)}><option value="fixed">Фиксированная</option><option value="random">Случайный диапазон</option></select></label>
          {values.delay_mode === 'random' ? <><label className="field"><span>Минимальная задержка, секунд</span><input type="number" min="0" value={Number(values.delay_min_seconds || 0)} onChange={event => set('delay_min_seconds', Number(event.target.value))} /></label><label className="field"><span>Максимальная задержка, секунд</span><input type="number" min="0" value={Number(values.delay_max_seconds || 0)} onChange={event => set('delay_max_seconds', Number(event.target.value))} /></label></> : <label className="field"><span>Задержка между группами, секунд</span><input type="number" min="0" value={Number(values.delay_seconds || 0)} onChange={event => set('delay_seconds', Number(event.target.value))} /></label>}
          <label className="field"><span>Минимум временных повторов</span><input type="number" min="1" max="10" value={Number(values.retry_min_attempts || 1)} onChange={event => set('retry_min_attempts', Number(event.target.value))} /><small>Минимальная граница диапазона повторов при временной ошибке VK.</small></label>
          <label className="field"><span>Максимум временных повторов</span><input type="number" min="1" max="10" value={Number(values.retry_max_attempts || 4)} onChange={event => set('retry_max_attempts', Number(event.target.value))} /><small>Максимальная граница диапазона повторов при временной ошибке VK.</small></label></div>
        <div className="settings-subsection"><div className="settings-section-head settings-section-head--compact"><div className="settings-icon settings-icon--violet"><MessageSquareText /></div><div><h2>Тексты обращений</h2><p>Один общий текст: сначала ЛС, предложка используется как запасной способ</p></div></div><MessageVariantsEditor label="Общий текст обращения" values={list('message_texts', 'message_text')} onChange={items => set('message_texts', items)} /></div>
      </Card>}

      {activeSection === 'messages' && <Card className="settings-card" role="tabpanel"><div className="settings-section-head"><div className="settings-icon settings-icon--violet"><MessageSquareText /></div><div><h2>Сообщения</h2><p>Синхронизация встроенных диалогов VK</p></div></div>
        <div className="settings-grid"><label className="field"><span>Синхронизация сообщений, секунд</span><input type="number" min="5" max="3600" value={Number(values.inbox_sync_seconds || 30)} onChange={event => set('inbox_sync_seconds', Number(event.target.value))} /><small>Безопасный диапазон: от 5 секунд до 1 часа.</small></label></div>
      </Card>}

      {activeSection === 'data' && <Card className="settings-card" role="tabpanel"><div className="settings-section-head"><div className="settings-icon settings-icon--green"><DatabaseBackup /></div><div><h2>Данные и резервные копии</h2><p>База, токены и история хранятся локально</p></div><Button variant="secondary" loading={createBackup.isPending} onClick={() => createBackup.mutate()}><DatabaseBackup size={16} />Создать копию</Button></div><div className="info-row"><span>Автоматическое восстановление</span><b>Включено</b></div><div className="info-row"><span>Режим SQLite</span><b>WAL + транзакции</b></div><div className="info-row"><span>Защита токенов</span><b>Системное хранилище ключей</b></div><div className="backup-list"><strong>Последние копии</strong>{backups.data?.length ? backups.data.slice(0, 5).map(row => <div key={row.name}><span>{formatLocalDateTime(row.created_at)}</span><code>{row.name}</code><b>{Math.max(1, Math.round(row.size / 1024))} КБ</b></div>) : <p>Копии появятся автоматически при запуске приложения.</p>}</div></Card>}

      {activeSection === 'extra' && <Card className="settings-card" role="tabpanel"><div className="settings-section-head"><div className="settings-icon"><Wrench /></div><div><h2>Дополнительно</h2><p>Масштаб интерфейса на этом компьютере</p></div></div><div className="settings-grid"><label className="field"><span>Масштаб интерфейса: {draftUiScalePercent}%</span><input type="range" min="75" max="300" step="5" value={draftUiScalePercent} onChange={event => setDraftUiScalePercent(Number(event.target.value))} /><small>Диапазон 75–300%. Изменение применяется к рабочей области только после сохранения.</small></label><div className="scale-save-row"><Button type="button" loading={saveUiScale.isPending} disabled={draftUiScalePercent === savedUiScalePercent} onClick={() => saveUiScale.mutate()}><Save size={16} />Сохранить</Button><small>Сохранённый масштаб: {savedUiScalePercent}%</small></div></div></Card>}
    </div></div>
  </div>
}