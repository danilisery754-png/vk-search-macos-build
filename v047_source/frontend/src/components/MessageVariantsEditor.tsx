import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { Button } from './ui'

export function MessageVariantsEditor({ label, values, onChange }: {
  label: string
  values: string[]
  onChange: (values: string[]) => void
}) {
  const update = (index: number, value: string) => onChange(values.map((item, itemIndex) => itemIndex === index ? value : item))
  const remove = (index: number) => onChange(values.filter((_, itemIndex) => itemIndex !== index))
  const move = (index: number, offset: -1 | 1) => {
    const target = index + offset
    if (target < 0 || target >= values.length) return
    const next = [...values]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next)
  }

  return <section className="message-variants">
    <header><div><h3>{label}</h3><p>Для каждой группы выбирается один закреплённый вариант</p></div><Button type="button" variant="secondary" onClick={() => onChange([...values, ''])}><Plus size={15} />Добавить вариант</Button></header>
    <div className="message-variant-list message-variant-list--scroll">{values.map((value, index) => <article className={`message-variant ${index === 0 ? 'message-variant--primary' : 'message-variant--compact'}`} key={index}>
      <div className="message-variant-head"><strong>Вариант {index + 1}</strong><div>
        <button type="button" className="icon-button" aria-label={`Переместить вариант ${index + 1} вверх`} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp size={15} /></button>
        <button type="button" className="icon-button" aria-label={`Переместить вариант ${index + 1} вниз`} disabled={index === values.length - 1} onClick={() => move(index, 1)}><ArrowDown size={15} /></button>
        <button type="button" className="icon-button danger-text" aria-label={`Удалить вариант ${index + 1}`} disabled={values.length === 1} onClick={() => remove(index)}><Trash2 size={15} /></button>
      </div></div>
      <textarea aria-label={`${label}, вариант ${index + 1}`} value={value} onChange={event => update(index, event.target.value)} />
    </article>)}</div>
  </section>
}
