import { describe, expect, it } from 'vitest'
import { displayToNormalized, normalizedToDisplay, normalizeBox, normalizePoint } from './geometry'

describe('normalized coordinate transforms', () => {
  it('maps between source-normalized and letterboxed display coordinates', () => {
    const transform = { sourceWidth: 1920, sourceHeight: 1080, displayWidth: 400, displayHeight: 400 }
    expect(normalizedToDisplay({ x: 0.5, y: 0.5 }, transform)).toEqual({ x: 200, y: 200 })
    expect(displayToNormalized({ x: 200, y: 87.5 }, transform)).toEqual({ x: 0.5, y: 0 })
  })

  it('clamps points and orders boxes into valid normalized geometry', () => {
    expect(normalizePoint({ x: -1, y: 2 })).toEqual({ x: 0, y: 1 })
    expect(normalizeBox({ x1: 0.8, y1: 0.9, x2: 0.2, y2: 0.1 })).toEqual({ x1: 0.2, y1: 0.1, x2: 0.8, y2: 0.9 })
  })
})
