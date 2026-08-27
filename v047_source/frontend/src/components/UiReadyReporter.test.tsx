import { render, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import UiReadyReporter from './UiReadyReporter'

describe('UiReadyReporter', () => {
  it('marks the production UI ready only after React mounts', async () => {
    window.__VK_UI_BOOTED__ = false
    render(<UiReadyReporter />)
    await waitFor(() => expect(window.__VK_UI_BOOTED__).toBe(true))
  })
})
