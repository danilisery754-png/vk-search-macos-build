import { useLayoutEffect, useRef, type PropsWithChildren } from 'react'
import { useLocation } from 'react-router-dom'
import { useSessionUiStore } from './SessionUiStore'

interface ViewportScrollSnapshot {
  left: number
  top: number
}

function safeCoordinate(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}

export default function SessionViewportScroll({ children }: PropsWithChildren) {
  const location = useLocation()
  const uiStore = useSessionUiStore()
  const viewportRef = useRef<HTMLDivElement>(null)
  const scrollKey = `viewport-scroll:${location.pathname}`

  useLayoutEffect(() => {
    const element = viewportRef.current
    if (!element) return
    const remembered = uiStore.read<ViewportScrollSnapshot>(scrollKey)
    element.scrollLeft = safeCoordinate(remembered?.left)
    element.scrollTop = safeCoordinate(remembered?.top)
  }, [scrollKey, uiStore])

  return <div
    ref={viewportRef}
    className="app-viewport"
    data-testid="app-viewport"
    style={{ overflow: 'auto' }}
    onScroll={event => uiStore.write<ViewportScrollSnapshot>(scrollKey, {
      left: event.currentTarget.scrollLeft,
      top: event.currentTarget.scrollTop,
    })}
  >{children}</div>
}
