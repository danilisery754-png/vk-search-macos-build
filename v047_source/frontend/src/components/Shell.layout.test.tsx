import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/styles/global.css'), 'utf8')

describe('desktop shell layout', () => {
  it('bounds workspace and main content to the viewport', () => {
    expect(css).toMatch(/\.workspace\s*\{[^}]*min-height:\s*0[^}]*overflow:\s*hidden/s)
    expect(css).toMatch(/\.workspace main\s*\{[^}]*min-height:\s*0[^}]*overflow:\s*hidden/s)
    expect(css).toMatch(/\.page\s*\{[^}]*height:\s*100%[^}]*min-height:\s*0[^}]*overflow:\s*auto/s)
  })
})
