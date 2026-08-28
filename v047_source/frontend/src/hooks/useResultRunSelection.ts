import { useEffect, useMemo, useState } from 'react'
import { useSessionUiStore } from '../components/SessionUiStore'

interface RunSelectionSnapshot {
  selectedRunId?: number | null
  [key: string]: unknown
}

function normalizeRememberedRun(value: unknown): number | null {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null
}

export function useResultRunSelection(
  currentRunId: number | null,
  availableRunIds: number[] = [],
  ready = true,
  sessionKey = 'results',
) {
  const uiStore = useSessionUiStore()
  const [selectedRunId, setSelectedRunId] = useState<number | null>(() => normalizeRememberedRun(uiStore.read<RunSelectionSnapshot>(sessionKey)?.selectedRunId))
  const validIds = useMemo(() => new Set(availableRunIds), [availableRunIds])
  const validKey = availableRunIds.join(',')

  function persist(value: number | null) {
    setSelectedRunId(value)
    const previous = uiStore.read<RunSelectionSnapshot>(sessionKey) || {}
    uiStore.write<RunSelectionSnapshot>(sessionKey, { ...previous, selectedRunId: value })
  }

  useEffect(() => {
    if (!ready) return
    if (currentRunId == null) {
      if (!availableRunIds.length && selectedRunId !== null) persist(null)
      return
    }
    if (selectedRunId != null && (!availableRunIds.length || validIds.has(selectedRunId))) return
    persist(currentRunId)
    // validKey tracks set contents while uiStore/sessionKey are stable for a mounted page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRunId, ready, validKey, sessionKey])

  function selectRun(id: number) {
    persist(id)
  }

  function returnToCurrent() {
    persist(currentRunId)
  }

  return { selectedRunId, selectRun, returnToCurrent }
}
