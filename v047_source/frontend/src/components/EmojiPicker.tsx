import { useMemo, useState } from 'react'

const extraSequences = [
  '❤️','☺️','☹️','☀️','☁️','☕','✈️','✉️','✌️','✍️','⭐','❄️','☘️','⚽','⚡','☔','☂️','⌚','⌛','⏰','☎️','✂️','✅','❌','❗','❓',
  '👨‍👩‍👧‍👦','👨‍👩‍👧','👩‍👩‍👧‍👦','👨‍👨‍👧‍👦','👩‍❤️‍👩','👨‍❤️‍👨','👩‍❤️‍💋‍👨','👩‍🚀','👨‍🚀','👩‍💻','👨‍💻','🏳️‍🌈','🏳️‍⚧️','🏴‍☠️',
]

function unicodeEmoji(): string[] {
  const result: string[] = []
  const pictographic = /\p{Extended_Pictographic}/u
  for (let code = 0x00a9; code <= 0x1faff; code += 1) {
    const char = String.fromCodePoint(code)
    if (pictographic.test(char)) result.push(char)
  }
  // Regional-indicator pairs cover all Unicode flag emoji without a remote dataset.
  for (let first = 0x1f1e6; first <= 0x1f1ff; first += 1) {
    for (let second = 0x1f1e6; second <= 0x1f1ff; second += 1) {
      result.push(String.fromCodePoint(first, second))
    }
  }
  for (const key of ['0','1','2','3','4','5','6','7','8','9','#','*']) result.push(`${key}\uFE0F\u20E3`)
  return [...new Set([...extraSequences, ...result])]
}

let cache: string[] | null = null
function allEmoji() { return cache ||= unicodeEmoji() }

function category(emoji: string) {
  const code = emoji.codePointAt(0) || 0
  if (code >= 0x1f600 && code <= 0x1f64f) return 'Лица'
  if ((code >= 0x1f466 && code <= 0x1f487) || (code >= 0x1f590 && code <= 0x1f64f)) return 'Люди'
  if (code >= 0x1f300 && code <= 0x1f5ff) return 'Природа'
  if (code >= 0x1f680 && code <= 0x1f6ff) return 'Места'
  if (code >= 0x1f1e6 && code <= 0x1f1ff) return 'Флаги'
  return 'Остальные'
}

export default function EmojiPicker({ onInsert }: { onInsert: (emoji: string) => void }) {
  const [tab, setTab] = useState('Лица')
  const tabs = ['Лица', 'Люди', 'Природа', 'Места', 'Флаги', 'Остальные']
  const values = useMemo(() => allEmoji().filter(value => category(value) === tab), [tab])
  return <div className="emoji-picker" role="dialog" aria-label="Смайлики">
    <div className="emoji-tabs">{tabs.map(value => <button key={value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)} type="button">{value}</button>)}</div>
    <div className="emoji-grid">{values.map((emoji, index) => <button key={`${emoji}-${index}`} type="button" title={`Emoji U+${(emoji.codePointAt(0) || 0).toString(16).toUpperCase()}`} onMouseDown={event => event.preventDefault()} onClick={() => onInsert(emoji)}>{emoji}</button>)}</div>
  </div>
}
