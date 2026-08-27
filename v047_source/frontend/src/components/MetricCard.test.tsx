import { render, screen } from '@testing-library/react'
import { Activity } from 'lucide-react'
import { describe, expect, it } from 'vitest'
import { MetricCard } from './MetricCard'

describe('MetricCard', () => {
  it('keeps a long label and its value available in the same card', () => {
    render(<MetricCard label="Сейчас обрабатывается" value={123456} icon={Activity} color="amber" />)

    const card = screen.getByRole('group', { name: 'Сейчас обрабатывается' })
    expect(card).toHaveTextContent('Сейчас обрабатывается')
    expect(card).toHaveTextContent(/123\s456/)
  })
})
