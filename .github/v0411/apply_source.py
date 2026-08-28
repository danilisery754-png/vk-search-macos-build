from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding='utf-8')
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly one match, found {count}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


hook = ROOT / 'v047_source/frontend/src/hooks/useAutoGrowTextarea.ts'
replace_once(
    hook,
    """export function resizeTextarea(textarea: HTMLTextAreaElement | null): void {
  if (!textarea) return
  textarea.style.height = 'auto'
  const computed = getComputedStyle(textarea)
  const lineHeight = parseFloat(computed.lineHeight) || 20
  const paddingTop = parseFloat(computed.paddingTop) || 0
  const paddingBottom = parseFloat(computed.paddingBottom) || 0
  const maxHeight = (lineHeight * 6) + paddingTop + paddingBottom
  const nextHeight = Math.min(textarea.scrollHeight, maxHeight)
  textarea.style.height = `${nextHeight}px`
  textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden'
}
""",
    """export function resizeTextarea(textarea: HTMLTextAreaElement | null): void {
  if (!textarea) return
  textarea.style.height = 'auto'
  textarea.style.height = `${textarea.scrollHeight}px`
  textarea.style.overflowY = 'hidden'
}
""",
)

inbox = ROOT / 'v047_source/frontend/src/pages/InboxPage.tsx'
replace_once(
    inbox,
    "const accountNames = new Map((accounts.data || []).map(account => [account.id, account.display_name]))",
    "const accountNames = new Map((accounts.data || []).map(account => [account.id, String(account.note || '').trim() || account.display_name]))",
)
replace_once(
    inbox,
    "            <div className=\"reply-account\">От: <strong>{replyAccount?.note || replyAccount?.name || activeDialog?.account_name || 'аккаунт'}</strong></div>\n",
    "",
)
replace_once(
    inbox,
    "              <Button type=\"submit\" disabled={!reply.trim()} loading={send.isPending}><Send size={17} />Отправить</Button>",
    "              <Button type=\"submit\" aria-label=\"Отправить\" disabled={!reply.trim()} loading={send.isPending}><Send size={17} /></Button>",
)

css = ROOT / 'v047_source/frontend/src/styles/v0410.css'
replace_once(
    css,
    """/* Compact messenger composer: one line initially, grows through JS up to six lines. */
.composer {
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) auto !important;
  align-items: end;
}

.composer textarea.composer-input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 32px !important;
  max-height: 132px;
  height: 32px;
  padding: 6px 10px !important;
  line-height: 20px;
  resize: none;
  overflow-y: hidden;
  align-self: end;
}

.composer-control-stack {
  align-self: end;
  min-width: 92px;
  width: 92px;
}
""",
    """/* Compact messenger composer: one line initially, then grows with its content without an inner scrollbar. */
.composer {
  min-width: 0;
  grid-template-columns: minmax(0, 1fr) auto !important;
  align-items: end;
}

.composer textarea.composer-input {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: 32px !important;
  height: 32px;
  padding: 6px 10px !important;
  line-height: 20px;
  resize: none;
  overflow-y: hidden !important;
  align-self: end;
}

.composer-control-stack {
  align-self: end;
  min-width: 40px;
  width: 40px;
}

.composer-control-stack > .button[type='submit'] {
  width: 40px;
  min-width: 40px;
  height: 40px;
  padding: 0;
}
""",
)
replace_once(
    css,
    """.dialog-account-toggle {
  flex: 1 1 auto;
  min-width: 0;
}

.dialog-account-drag-handle {
  flex: 0 0 auto;
  cursor: grab;
}
""",
    """.dialog-account-toggle {
  width: auto !important;
  flex: 1 1 auto;
  min-width: 0;
}

.dialog-account-drag-handle {
  width: 28px !important;
  min-width: 28px;
  flex: 0 0 28px;
  padding: 0 !important;
  display: grid;
  place-items: center;
  cursor: grab;
}
""",
)

print('Applied v0.4.11 Inbox source edits')
