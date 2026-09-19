import type { BoxN, PointN } from '@vision-app/contracts'

export type { BoxN, PointN }

export interface DisplayTransform {
  sourceWidth: number
  sourceHeight: number
  displayWidth: number
  displayHeight: number
}

export interface FittedDisplay {
  scale: number
  offsetX: number
  offsetY: number
  contentWidth: number
  contentHeight: number
}

const finite = (value: number, fallback = 0) => Number.isFinite(value) ? value : fallback
const clamp01 = (value: number) => Math.min(1, Math.max(0, finite(value)))

export function normalizePoint(point: PointN): PointN {
  return { x: clamp01(point.x), y: clamp01(point.y) }
}

export function normalizeBox(box: BoxN): BoxN {
  const x1 = clamp01(Math.min(box.x1, box.x2))
  const y1 = clamp01(Math.min(box.y1, box.y2))
  const x2 = clamp01(Math.max(box.x1, box.x2))
  const y2 = clamp01(Math.max(box.y1, box.y2))
  return { x1, y1, x2, y2 }
}

export function fitDisplay(transform: DisplayTransform): FittedDisplay {
  const sourceWidth = Math.max(1, finite(transform.sourceWidth, 1))
  const sourceHeight = Math.max(1, finite(transform.sourceHeight, 1))
  const scale = Math.min(transform.displayWidth / sourceWidth, transform.displayHeight / sourceHeight)
  const contentWidth = sourceWidth * scale
  const contentHeight = sourceHeight * scale
  return {
    scale,
    contentWidth,
    contentHeight,
    offsetX: (transform.displayWidth - contentWidth) / 2,
    offsetY: (transform.displayHeight - contentHeight) / 2,
  }
}

export function normalizedToDisplay(point: PointN, transform: DisplayTransform): PointN {
  const fit = fitDisplay(transform)
  const normalized = normalizePoint(point)
  return { x: fit.offsetX + normalized.x * fit.contentWidth, y: fit.offsetY + normalized.y * fit.contentHeight }
}

export function displayToNormalized(point: PointN, transform: DisplayTransform): PointN {
  const fit = fitDisplay(transform)
  return normalizePoint({ x: (point.x - fit.offsetX) / fit.contentWidth, y: (point.y - fit.offsetY) / fit.contentHeight })
}
