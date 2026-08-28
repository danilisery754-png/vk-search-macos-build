import { describe, expect, it } from 'vitest'
import { resizeTextarea } from './useAutoGrowTextarea'

describe('v0.4.11 composer auto-grow', () => {
  it('grows to the full content height and never enables an internal vertical scrollbar', () => {
    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    Object.defineProperty(textarea, 'scrollHeight', { configurable: true, value: 286 })

    resizeTextarea(textarea)

    expect(textarea.style.height).toBe('286px')
    expect(textarea.style.overflowY).toBe('hidden')
    textarea.remove()
  })
})
