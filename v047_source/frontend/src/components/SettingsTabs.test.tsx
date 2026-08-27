import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SettingsTabs } from './SettingsTabs'

describe('SettingsTabs', () => {
  it('changes the active panel without using document anchors', () => {
    const onSelect = vi.fn()

    render(<SettingsTabs active="sending" onSelect={onSelect} />)

    expect(screen.getAllByRole('tab')).toHaveLength(4)
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Рассылка' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.click(screen.getByRole('tab', { name: 'Сообщения' }))
    expect(onSelect).toHaveBeenCalledWith('messages')
  })
})
