import { useEffect, useMemo, useState } from 'react'

const STORAGE_KEY = 'vk-outreach:selected-run'

function readStoredRun(): number | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = Number(raw)
    return Number.isInteger(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

export function useResultRunSelection(currentRunId: number | null, availableRunIds: number[] = [], ready = true) {
  const [selectedRunId, setSelectedRunId] = useState<number | null>(() => readStoredRun())
  const validIds = useMemo(() => new Set(availableRunIds), [availableRunIds])
  const validKey = availableRunIds.join(',')

  useEffect(() => {
    if (!ready) return
    if (currentRunId == null) {
      if (!availableRunIds.length) setSelectedRunId(null)
      return
    }
    setSelectedRunId(previous => {
      if (previous != null && (!availableRunIds.length || validIds.has(previous))) return previous
      try { sessionStorage.setItem(STORAGE_KEY, String(currentRunId)) } catch { /* storage unavailable */ }
      return currentRunId
    })
    // validKey provides a stable dependency for the ID set contents.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentRunId, ready, validKey])

  function selectRun(id: number) {
    setSelectedRunId(id)
    try { sessionStorage.setItem(STORAGE_KEY, String(id)) } catch { /* storage unavailable */ }
  }

  function returnToCurrent() {
    if (currentRunId == null) {
      setSelectedRunId(null)
      try { sessionStorage.removeItem(STORAGE_KEY) } catch { /* storage unavailable */ }
      return
    }
    selectRun(currentRunId)
  }

  return { selectedRunId, selectRun, returnToCurrent }
}
