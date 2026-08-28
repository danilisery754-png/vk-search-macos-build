import type { CSSProperties } from 'react'

export const UI_SCALE_MIN = .75
export const UI_SCALE_MAX = 3

export function normalizeUiScale(value: unknown): number {
  const parsed = Number(value)
  return Math.min(UI_SCALE_MAX, Math.max(UI_SCALE_MIN, Number.isFinite(parsed) ? parsed : 1))
}

export function fullAppScaleStyle(scaleValue: number): CSSProperties {
  const scale = normalizeUiScale(scaleValue)
  const compensated = scale < 1 ? `${100 / scale}%` : '100%'
  return {
    '--ui-scale': String(scale),
    zoom: scale,
    width: compensated,
    height: compensated,
    minWidth: compensated,
    minHeight: compensated,
  } as CSSProperties
}

export function viewportToLogical(value: number, scaleValue: number): number {
  return value / normalizeUiScale(scaleValue)
}

export interface OverlayPositionInput {
  clientX: number
  clientY: number
  overlayWidth: number
  overlayHeight: number
  viewportWidth: number
  viewportHeight: number
  scale: number
  padding?: number
  rootLeft?: number
  rootTop?: number
}

export interface OverlayPosition {
  left: number
  top: number
}

export function clampOverlayPosition(input: OverlayPositionInput): OverlayPosition {
  const scale = normalizeUiScale(input.scale)
  const padding = Math.max(0, input.padding ?? 8)
  const rootLeft = Number.isFinite(input.rootLeft) ? Number(input.rootLeft) : 0
  const rootTop = Number.isFinite(input.rootTop) ? Number(input.rootTop) : 0
  const minLeft = (padding - rootLeft) / scale
  const minTop = (padding - rootTop) / scale
  const maxLeft = Math.max(minLeft, (input.viewportWidth - padding - Math.max(0, input.overlayWidth) - rootLeft) / scale)
  const maxTop = Math.max(minTop, (input.viewportHeight - padding - Math.max(0, input.overlayHeight) - rootTop) / scale)
  const desiredLeft = (input.clientX - rootLeft) / scale
  const desiredTop = (input.clientY - rootTop) / scale

  return {
    left: Math.min(maxLeft, Math.max(minLeft, desiredLeft)),
    top: Math.min(maxTop, Math.max(minTop, desiredTop)),
  }
}
