import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CalibrationEditor, STANDARD_GEOMETRIES } from './CalibrationEditor'

describe('CalibrationEditor', () => {
  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  })

  it('renders the standard geometry over the video without drawing tools', () => {
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={640} sourceHeight={360} onConfirm={vi.fn()} />)
    expect(screen.getByLabelText('Calibration drawing canvas')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /draw|clear|sample/i })).not.toBeInTheDocument()
  })

  it('submits the standard geometry once and disables confirmation', () => {
    const onConfirm = vi.fn()
    render(<CalibrationEditor src="fixture.mp4" sourceWidth={640} sourceHeight={360} onConfirm={onConfirm} />)
    const confirm = screen.getByRole('button', { name: 'Confirm calibration' })
    expect(confirm).toBeEnabled()
    fireEvent.click(confirm)
    expect(onConfirm).toHaveBeenCalledWith(STANDARD_GEOMETRIES)
    expect(confirm).toBeDisabled()
    expect(screen.getByText('Calibration confirmed.')).toBeInTheDocument()
  })
})
