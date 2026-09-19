import { useState } from 'react'
import { Button } from '../../ui'
import { CalibrationCanvas, type OverlayGeometry } from './CalibrationCanvas'
import { VideoPlayer } from './VideoPlayer'

export interface CalibrationEditorProps {
  src: string
  sourceWidth: number
  sourceHeight: number
  fps?: number
  onConfirm: (geometries: OverlayGeometry[]) => void
}

/** Standard scene geometry: a vertical stop line and the signal region it governs. */
export const STANDARD_GEOMETRIES: OverlayGeometry[] = [
  { id: 'stop-line', kind: 'line', label: 'stop-line', points: [{ x: 0.5, y: 0.15 }, { x: 0.5, y: 0.85 }] },
  { id: 'roi', kind: 'polygon', label: 'roi', points: [{ x: 0.87, y: 0.05 }, { x: 0.97, y: 0.05 }, { x: 0.97, y: 0.2 }, { x: 0.87, y: 0.2 }] },
]

export function CalibrationEditor({ src, sourceWidth, sourceHeight, fps, onConfirm }: CalibrationEditorProps) {
  const [confirmed, setConfirmed] = useState(false)

  return <section aria-label="Calibration editor">
    <h2>Confirm scene calibration</h2>
    <VideoPlayer src={src} fps={fps} ariaLabel="Calibration video">
      <CalibrationCanvas width={sourceWidth} height={sourceHeight} sourceWidth={sourceWidth} sourceHeight={sourceHeight} geometries={STANDARD_GEOMETRIES} />
    </VideoPlayer>
    {confirmed && <p role="status">Calibration confirmed.</p>}
    <Button type="button" disabled={confirmed} onClick={() => { onConfirm(STANDARD_GEOMETRIES); setConfirmed(true) }}>Confirm calibration</Button>
  </section>
}
