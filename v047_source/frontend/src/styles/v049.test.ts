import { describe, expect, it } from 'vitest'
import css from './v049.css?raw'

describe('v0.4.9 layout CSS', () => {
  it('pins the application shell to the exact host viewport without 100vh overflow', () => {
    expect(css).toContain('#root')
    expect(css).toMatch(/#root\s*\{[^}]*position:\s*fixed[^}]*inset:\s*0/s)
    expect(css).toMatch(/\.app-shell\s*\{[^}]*height:\s*100%/s)
    expect(css).toMatch(/\.workspace main\s*\{[^}]*overflow:\s*auto/s)
    expect(css).not.toContain('100vh')
  })

  it('never pre-shrinks high zoom using inverse scale dimensions', () => {
    expect(css).not.toContain('calc(100% / var(--work-scale))')
    expect(css).toMatch(/\.work-scale-root\s*\{[^}]*transform-origin:\s*top left/s)
  })

  it('keeps dialog preview to one line and stacks composer controls vertically', () => {
    expect(css).toMatch(/\.dialog-preview\s*\{[^}]*white-space:\s*nowrap[^}]*text-overflow:\s*ellipsis/s)
    expect(css).toMatch(/\.composer-control-stack\s*\{[^}]*flex-direction:\s*column/s)
  })
})
