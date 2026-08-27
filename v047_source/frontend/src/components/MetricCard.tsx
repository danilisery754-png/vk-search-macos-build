import type { LucideIcon } from 'lucide-react'
import { Card } from './ui'

const numberFormatter = new Intl.NumberFormat('ru-RU')

export function MetricCard({ label, value, icon: Icon, color }: {
  label: string
  value: number
  icon: LucideIcon
  color: 'blue' | 'violet' | 'amber' | 'green' | 'red' | 'cyan'
}) {
  return <Card className="metric-card" role="group" aria-label={label}>
    <div className={`metric-icon metric-icon--${color}`}><Icon size={21} /></div>
    <div className="metric-copy"><span>{label}</span><strong>{numberFormatter.format(value)}</strong></div>
  </Card>
}
