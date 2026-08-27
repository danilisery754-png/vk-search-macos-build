import { useEffect } from 'react'

declare global {
  interface Window {
    __VK_UI_BOOTED__?: boolean
  }
}

export default function UiReadyReporter() {
  useEffect(() => {
    window.__VK_UI_BOOTED__ = true
  }, [])
  return null
}
