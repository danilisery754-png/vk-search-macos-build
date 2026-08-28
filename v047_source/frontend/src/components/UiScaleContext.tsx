import { createContext, useContext, type PropsWithChildren } from 'react'
import { normalizeUiScale } from '../utils/uiScale'

const UiScaleContext = createContext(1)

export function UiScaleProvider({ value, children }: PropsWithChildren<{ value: number }>) {
  return <UiScaleContext.Provider value={normalizeUiScale(value)}>{children}</UiScaleContext.Provider>
}

export function useUiScale(): number {
  return useContext(UiScaleContext)
}
