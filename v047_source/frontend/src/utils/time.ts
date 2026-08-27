function normalizeApiTimestamp(value: string | null | undefined): string | null {
  const text = String(value || '').trim()
  if (!text) return null
  // Backend stores historical SQLite timestamps as UTC-naive. Treat an offsetless
  // API value as UTC, then let Intl render in the OS/browser timezone.
  if (/^\d{4}-\d{2}-\d{2}T/.test(text) && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) return `${text}Z`
  return text
}

function asDate(value: string | null | undefined): Date | null {
  const normalized = normalizeApiTimestamp(value)
  if (!normalized) return null
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatLocalDateTime(value: string | null | undefined): string {
  const date = asDate(value)
  return date ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }).format(date) : '—'
}

export function formatLocalDate(value: string | null | undefined): string {
  const date = asDate(value)
  return date ? new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short' }).format(date) : '—'
}

export function formatLocalTime(value: string | null | undefined): string {
  const date = asDate(value)
  return date ? new Intl.DateTimeFormat('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date) : '—'
}
