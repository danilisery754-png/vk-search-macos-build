import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(process.cwd(), 'src/styles/v0410.css'), 'utf8')

describe('v0.4.11 Inbox CSS contracts', () => {
  it('prevents the drag handle from inheriting the legacy full-width header button rule', () => {
    expect(css).toMatch(/\.dialog-account-drag-handle\s*\{[^}]*width:\s*28px[^}]*min-width:\s*28px/s)
    expect(css).toMatch(/\.dialog-account-toggle\s*\{[^}]*width:\s*auto\s*!important[^}]*flex:\s*1\s+1\s+auto/s)
  })

  it('keeps the message textarea free of an internal vertical scrollbar and height cap', () => {
    const composerRule = css.match(/\.composer textarea\.composer-input\s*\{([^}]*)\}/s)?.[1] || ''
    expect(composerRule).toMatch(/overflow-y:\s*hidden\s*!important/)
    expect(composerRule).not.toMatch(/max-height:/)
  })

  it('keeps the three composer actions compact while leaving the text field the flexible column', () => {
    expect(css).toMatch(/\.composer-control-stack\s*\{[^}]*min-width:\s*40px[^}]*width:\s*40px/s)
    expect(css).toMatch(/\.composer-control-stack\s*>\s*\.button\[type=['"]submit['"]\]\s*\{[^}]*width:\s*40px[^}]*padding:\s*0/s)
  })
})
