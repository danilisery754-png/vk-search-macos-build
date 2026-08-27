import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CirclePause, CirclePlay, OctagonX } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '../api/client'
import type { WorkState } from '../types'
import { Button } from './ui'

type ActionName = 'start' | 'pause' | 'resume' | 'stop'

export default function WorkControls({ state }: { state: WorkState }) {
  const client = useQueryClient()
  const mutation = useMutation({
    mutationFn: (name: ActionName) => api(`/work/${name}`, {
      method: 'POST',
      ...(name === 'start' ? { body: JSON.stringify({ mode: 'respect_limits' }) } : {}),
    }),
    onSuccess: (_data, name) => {
      toast.success(name === 'start' || name === 'resume' ? 'Работа запущена' : 'Состояние изменено')
      client.invalidateQueries()
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const running = state === 'running'
  const resumable = ['paused', 'needs_attention', 'requires_login', 'waiting_limit'].includes(state)
  const stoppable = ['running', 'paused', 'waiting_limit', 'needs_attention', 'requires_login'].includes(state)

  return <div className="window-work-controls" aria-label="Управление рассылкой">
    <Button className="window-control" disabled={running} loading={mutation.isPending} onClick={() => mutation.mutate('start')}><CirclePlay size={14} /><span>Запустить</span></Button>
    <Button className="window-control" variant="secondary" disabled={!running} onClick={() => mutation.mutate('pause')}><CirclePause size={14} /><span>Пауза</span></Button>
    <Button className="window-control" variant="secondary" disabled={!resumable} onClick={() => mutation.mutate('resume')}><CirclePlay size={14} /><span>Продолжить</span></Button>
    <Button className="window-control" variant="danger" disabled={!stoppable} onClick={() => { if (confirm('Корректно остановить текущую работу? Состояние и оставшиеся группы сохранятся.')) mutation.mutate('stop') }}><OctagonX size={14} /><span>Остановить</span></Button>
  </div>
}
