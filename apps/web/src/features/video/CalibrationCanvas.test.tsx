import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CalibrationCanvas } from './CalibrationCanvas'

const context = {
  clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(),
  stroke: vi.fn(), fill: vi.fn(), arc: vi.fn(), strokeRect: vi.fn(), setLineDash: vi.fn(),
}

describe('CalibrationCanvas', () => {
  beforeEach(() => {
    Object.values(context).forEach((mock) => { if (typeof mock === 'function') mock.mockClear() })
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  })

  it('renders points, boxes, lines, and polygons', () => {
    render(<CalibrationCanvas width={640} height={360} sourceWidth={640} sourceHeight={360} geometries={[
      { id: 'p', kind: 'point', point: { x: 0.5, y: 0.5 } },
      { id: 'b', kind: 'box', box: { x1: 0.1, y1: 0.1, x2: 0.2, y2: 0.2 } },
      { id: 'l', kind: 'line', points: [{ x: 0, y: 0 }, { x: 1, y: 1 }] },
      { id: 'z', kind: 'polygon', points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }] },
    ]} />)
    expect(context.arc).toHaveBeenCalled()
    expect(context.strokeRect).toHaveBeenCalledWith(64, 36, 64, 36)
    expect(context.lineTo).toHaveBeenCalled()
    expect(context.closePath).toHaveBeenCalled()
  })

  it.each([false, true])('accepts rapid endpoint clicks in either direction (reverse=%s)', (reverse) => {
    const onComplete = vi.fn()
    render(<CalibrationCanvas width={200} height={100} sourceWidth={200} sourceHeight={100} geometries={[]} tool="stop-line" onGeometryComplete={onComplete} />)
    const canvas = screen.getByLabelText('Calibration drawing canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => null })
    fireEvent.click(canvas, { clientX: 100, clientY: reverse ? 85 : 15, detail: 1 })
    fireEvent.click(canvas, { clientX: 100, clientY: reverse ? 15 : 85, detail: 2 })
    expect(onComplete).toHaveBeenCalledExactlyOnceWith({ kind: 'line', points: [{ x: 0.5, y: 0.15 }, { x: 0.5, y: 0.85 }] })
  })

  it.each([false, true])('creates a rectangle from opposite corners (reverse=%s)', (reverse) => {
    const onComplete = vi.fn()
    render(<CalibrationCanvas width={200} height={100} sourceWidth={200} sourceHeight={100} geometries={[]} tool="roi" onGeometryComplete={onComplete} />)
    const canvas = screen.getByLabelText('Calibration drawing canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => null })
    fireEvent.click(canvas, { clientX: reverse ? 190 : 144, clientY: reverse ? 25 : 5 })
    fireEvent.click(canvas, { clientX: reverse ? 144 : 190, clientY: reverse ? 5 : 25 })
    expect(onComplete).toHaveBeenCalledExactlyOnceWith({ kind: 'polygon', points: [
      { x: 0.72, y: 0.05 }, { x: 0.95, y: 0.05 }, { x: 0.95, y: 0.25 }, { x: 0.72, y: 0.25 },
    ] })
  })

  it('switches tool modes and emits completed normalized geometry', () => {
    const onComplete = vi.fn()
    render(<CalibrationCanvas width={200} height={100} sourceWidth={200} sourceHeight={100} geometries={[]} tool="stop-line" onGeometryComplete={onComplete} />)
    const canvas = screen.getByLabelText('Calibration drawing canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => null })
    fireEvent.click(canvas, { clientX: 20, clientY: 20 })
    fireEvent.click(canvas, { clientX: 180, clientY: 80 })
    expect(onComplete).toHaveBeenCalledWith({ kind: 'line', points: [{ x: 0.1, y: 0.2 }, { x: 0.9, y: 0.8 }] })
  })
})
