export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  if (!response.ok) {
    let message = `Ошибка ${response.status}`
    try {
      const payload = await response.json()
      message = payload.detail || payload.message || message
    } catch { /* ответ не JSON */ }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

export async function downloadExport(kind: 'success' | 'failed', mode: 'links' | 'tsv' | 'csv' | 'xlsx', selectedIds?: number[], runId?: number | null) {
  const response = await fetch(`/api/results/${kind}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode, selected_ids: selectedIds, run_id: runId ?? null }),
  })
  if (!response.ok) throw new Error('Не удалось подготовить экспорт')
  const blob = await response.blob()
  const disposition = response.headers.get('Content-Disposition') || ''
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1]
  const name = encoded ? decodeURIComponent(encoded) : `результаты.${mode === 'links' ? 'txt' : mode}`
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = name
  link.click()
  URL.revokeObjectURL(link.href)
}
