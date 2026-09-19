import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CalibrationEditor } from './CalibrationEditor'

describe('CalibrationEditor', () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  })

  it('switches geometry tool modes', () => {
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={640} sourceHeight={360} onConfirm={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Draw ROI' }))
    expect(screen.getByRole('button', { name: 'Draw ROI' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: 'Draw lane or zone' }))
    expect(screen.getByRole('button', { name: 'Draw lane or zone' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('keeps confirmation disabled until required geometry exists', () => {
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={640} sourceHeight={360} onConfirm={vi.fn()} />)
    expect(screen.getByRole('button', { name: 'Confirm calibration' })).toBeDisabled()
    expect(screen.getByText(/stop line and at least one ROI, lane, or zone/i)).toBeInTheDocument()
  })

  it('saves a rectangle after two opposite corners without a finish gesture', () => {
    const onConfirm = vi.fn()
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={200} sourceHeight={100} onConfirm={onConfirm} />)
    const canvas = screen.getByLabelText('Calibration drawing canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => null })
    fireEvent.click(screen.getByRole('button', { name: 'Draw stop line' }))
    fireEvent.click(canvas, { clientX: 100, clientY: 15 })
    fireEvent.click(canvas, { clientX: 100, clientY: 85 })
    fireEvent.click(screen.getByRole('button', { name: 'Draw ROI' }))
    fireEvent.click(canvas, { clientX: 144, clientY: 5 })
    expect(screen.getByText(/opposite corner/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Confirm calibration' })).toBeDisabled()
    fireEvent.click(canvas, { clientX: 190, clientY: 25 })
    expect(screen.getByRole('button', { name: 'Confirm calibration' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm calibration' }))
    expect(onConfirm).toHaveBeenCalledWith([
      expect.objectContaining({ kind: 'line', label: 'stop-line' }),
      expect.objectContaining({ kind: 'polygon', label: 'roi', points: [
        { x: 0.72, y: 0.05 }, { x: 0.95, y: 0.05 }, { x: 0.95, y: 0.25 }, { x: 0.72, y: 0.25 },
      ] }),
    ])
  })

  it('lets users clear an unfinished polygon even without saved geometry', () => {
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={200} sourceHeight={100} onConfirm={vi.fn()} />)
    const canvas = screen.getByLabelText('Calibration drawing canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => null })
    fireEvent.click(screen.getByRole('button', { name: 'Draw ROI' }))
    fireEvent.click(canvas, { clientX: 20, clientY: 20 })
    expect(screen.getByRole('button', { name: 'Clear geometry' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Clear geometry' }))
    expect(screen.getByRole('button', { name: 'Clear geometry' })).toBeDisabled()
    expect(screen.queryByText(/Rectangle unfinished/)).not.toBeInTheDocument()
  })

  it('offers one-click calibration for the bundled sample video', () => {
    const onConfirm = vi.fn()
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={320} sourceHeight={240} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: 'Use sample-video calibration' }))
    expect(screen.getByRole('button', { name: 'Confirm calibration' })).toBeEnabled()
    expect(onConfirm).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm calibration' }))
    expect(onConfirm).toHaveBeenCalledWith([
      expect.objectContaining({ label: 'stop-line', points: [{ x: 0.5, y: 0.15 }, { x: 0.5, y: 0.85 }] }),
      expect.objectContaining({ label: 'roi', kind: 'polygon', points: expect.any(Array) }),
    ])
  })

  it('replaces a redrawn stop line rather than keeping an obsolete one', () => {
    const onConfirm = vi.fn()
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={200} sourceHeight={100} onConfirm={onConfirm} />)
    fireEvent.click(screen.getByRole('button', { name: 'Use sample-video calibration' }))
    fireEvent.click(screen.getByRole('button', { name: 'Draw stop line' }))
    const canvas = screen.getByLabelText('Calibration drawing canvas')
    vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 200, height: 100, right: 200, bottom: 100, x: 0, y: 0, toJSON: () => null })
    fireEvent.click(canvas, { clientX: 120, clientY: 85 })
    fireEvent.click(canvas, { clientX: 120, clientY: 15 })
    fireEvent.click(screen.getByRole('button', { name: 'Confirm calibration' }))
    const shapes = onConfirm.mock.calls[0][0]
    expect(shapes.filter((shape: { kind: string }) => shape.kind === 'line')).toEqual([
      expect.objectContaining({ points: [{ x: 0.6, y: 0.15 }, { x: 0.6, y: 0.85 }] }),
    ])
  })

  it('enables confirmation for complete geometry and submits it once', () => {
    const onConfirm = vi.fn()
    const geometries = [
      { id: 'line', kind: 'line' as const, label: 'stop-line', points: [{ x: 0.1, y: 0.5 }, { x: 0.9, y: 0.5 }] },
      { id: 'roi', kind: 'polygon' as const, label: 'roi', points: [{ x: 0.1, y: 0.1 }, { x: 0.2, y: 0.1 }, { x: 0.2, y: 0.2 }] },
    ]
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={640} sourceHeight={360} initialGeometries={geometries} onConfirm={onConfirm} />)
    const confirm = screen.getByRole('button', { name: 'Confirm calibration' })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith(geometries)
    expect(confirm).toBeDisabled()
  })
})
