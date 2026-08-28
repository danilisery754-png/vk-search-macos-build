import { useLayoutEffect, type RefObject } from 'react'
import { useUiScale } from '../components/UiScaleContext'

export function resizeTextarea(textarea: HTMLTextAreaElement | null): void {
  if (!textarea) return
  textarea.style.height = 'auto'
  textarea.style.height = `${textarea.scrollHeight}px`
  textarea.style.overflowY = 'hidden'
}

export function useAutoGrowTextarea(ref: RefObject<HTMLTextAreaElement | null>, value: string): void {
  const uiScale = useUiScale()
  useLayoutEffect(() => {
    resizeTextarea(ref.current)
  }, [ref, uiScale, value])
}
