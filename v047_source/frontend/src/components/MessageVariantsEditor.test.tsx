import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MessageVariantsEditor } from './MessageVariantsEditor'

describe('MessageVariantsEditor', () => {
  it('appends a new editable variant', () => {
    const onChange = vi.fn()
    render(<MessageVariantsEditor label="ЛС" values={['Первый', 'Второй']} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Добавить вариант' }))

    expect(onChange).toHaveBeenCalledWith(['Первый', 'Второй', ''])
  })

  it('emits the complete list after editing', () => {
    const onChange = vi.fn()
    render(<MessageVariantsEditor label="ЛС" values={['Первый', 'Второй']} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('ЛС, вариант 2'), { target: { value: 'Изменённый' } })

    expect(onChange).toHaveBeenCalledWith(['Первый', 'Изменённый'])
  })

  it('moves and deletes variants without altering their text', () => {
    const onChange = vi.fn()
    const { rerender } = render(<MessageVariantsEditor label="ЛС" values={['Первый', 'Второй']} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Переместить вариант 1 вниз' }))
    expect(onChange).toHaveBeenLastCalledWith(['Второй', 'Первый'])

    rerender(<MessageVariantsEditor label="ЛС" values={['Первый', 'Второй']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Удалить вариант 2' }))
    expect(onChange).toHaveBeenLastCalledWith(['Первый'])
  })

  it('does not allow deleting the only remaining variant', () => {
    render(<MessageVariantsEditor label="ЛС" values={['Единственный']} onChange={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Удалить вариант 1' })).toBeDisabled()
  })
  it('marks the first variant as primary and additional variants as compact', () => {
    const values = Array.from({ length: 30 }, (_, i) => `Текст ${i + 1}`)
    const { container } = render(<MessageVariantsEditor label="ЛС" values={values} onChange={vi.fn()} />)
    expect(container.querySelectorAll('.message-variant')).toHaveLength(30)
    expect(container.querySelectorAll('.message-variant--primary')).toHaveLength(1)
    expect(container.querySelectorAll('.message-variant--compact')).toHaveLength(29)
    expect(container.querySelector('.message-variant-list')).toHaveClass('message-variant-list--scroll')
  })

})
