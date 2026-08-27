import { DatabaseBackup, MessageSquareText, Settings2, Wrench, type LucideIcon } from 'lucide-react'

export type SettingsSection = 'sending' | 'messages' | 'data' | 'extra'

const sections: Array<{ id: SettingsSection; label: string; icon: LucideIcon }> = [
  { id: 'sending', label: 'Рассылка', icon: Settings2 },
  { id: 'messages', label: 'Сообщения', icon: MessageSquareText },
  { id: 'data', label: 'Данные и экспорт', icon: DatabaseBackup },
  { id: 'extra', label: 'Дополнительно', icon: Wrench },
]

export function SettingsTabs({ active, onSelect }: { active: SettingsSection; onSelect: (section: SettingsSection) => void }) {
  return <nav className="settings-nav" aria-label="Разделы настроек" role="tablist">
    {sections.map(({ id, label, icon: Icon }) => <button
      key={id}
      type="button"
      role="tab"
      aria-selected={active === id}
      className={active === id ? 'active' : ''}
      onClick={() => onSelect(id)}
    ><Icon />{label}</button>)}
  </nav>
}
