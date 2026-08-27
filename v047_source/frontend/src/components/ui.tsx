import type { ButtonHTMLAttributes, HTMLAttributes, PropsWithChildren, ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'

export function Button({ variant = 'primary', loading, className = '', children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'danger' | 'ghost'; loading?: boolean }) {
  return <button className={`button button--${variant} ${className}`} disabled={loading || props.disabled} {...props}>
    {loading && <LoaderCircle size={16} className="spin" />}{children}
  </button>
}

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  return <header className="page-header">
    <div><h1>{title}</h1><p>{description}</p></div>
    {actions && <div className="page-actions">{actions}</div>}
  </header>
}

export function Card({ children, className = '', ...props }: PropsWithChildren<HTMLAttributes<HTMLElement>>) {
  return <section className={`card ${className}`} {...props}>{children}</section>
}

export function Status({ state, children }: PropsWithChildren<{ state: string }>) {
  const tone = state.includes('success') || state === 'sent' || state === 'ok' || state === 'working' ? 'success'
    : state.includes('error') || state === 'failed' || state === 'failed_final' ? 'danger'
      : state.includes('wait') || state === 'requires_login' || state === 'paused' ? 'warning' : 'neutral'
  return <span className={`status status--${tone}`}><i />{children}</span>
}

export function EmptyState({ icon, title, text, action }: { icon: ReactNode; title: string; text: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{text}</p>{action}</div>
}

export function Skeleton({ height = 20 }: { height?: number }) {
  return <div className="skeleton" style={{ height }} />
}
