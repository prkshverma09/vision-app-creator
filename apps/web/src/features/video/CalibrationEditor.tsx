import { useState } from 'react'
import type { PointN } from '@vision-app/contracts'
import { Button } from '../../ui'
import { CalibrationCanvas, type CompletedGeometry, type GeometryTool, type OverlayGeometry } from './CalibrationCanvas'
import { VideoPlayer } from './VideoPlayer'

export interface CalibrationEditorProps {
  src: string
  sourceWidth: number
  sourceHeight: number
  fps?: number
  initialGeometries?: OverlayGeometry[]
  onConfirm: (geometries: OverlayGeometry[]) => void
}

const tools: { mode: GeometryTool; label: string }[] = [
  { mode: 'select', label: 'Select' },
  { mode: 'stop-line', label: 'Draw stop line' },
  { mode: 'roi', label: 'Draw ROI' },
  { mode: 'lane-zone', label: 'Draw lane or zone' },
]

export function CalibrationEditor({ src, sourceWidth, sourceHeight, fps, initialGeometries = [], onConfirm }: CalibrationEditorProps) {
  const [tool, setTool] = useState<GeometryTool>('select')
  const [geometries, setGeometries] = useState<OverlayGeometry[]>(initialGeometries)
  const [confirmed, setConfirmed] = useState(false)
  const [draft, setDraft] = useState<PointN[]>([])
  const isPolygon = tool === 'lane-zone'
  const finishLabel = 'Finish lane or zone'

  const complete = (geometry: CompletedGeometry) => {
    const role = tool === 'stop-line' ? 'stop-line' : tool
    setGeometries((current) => [...current.filter(item => item.label !== role), { ...geometry, id: role, label: role }])
    setDraft([])
    setConfirmed(false)
  }
  const hasStopLine = geometries.some((geometry) => geometry.kind === 'line' && geometry.label === 'stop-line')
  const hasArea = geometries.some((geometry) => geometry.kind === 'polygon' && (geometry.label === 'roi' || geometry.label === 'lane-zone'))
  const canConfirm = hasStopLine && hasArea && draft.length === 0

  return <section aria-label="Calibration editor">
    <h2>Confirm scene calibration</h2>
    <p>Stop line: drag a line or click its two endpoints, in either order. ROI: drag a rectangle or click two diagonal corners. Both save automatically. To replace a shape, draw it again.</p>
    <Button type="button" onClick={() => {
      setGeometries([
        { id: 'stop-line', kind: 'line', label: 'stop-line', points: [{ x: 0.5, y: 0.15 }, { x: 0.5, y: 0.85 }] },
        { id: 'roi', kind: 'polygon', label: 'roi', points: [{ x: 0.87, y: 0.05 }, { x: 0.97, y: 0.05 }, { x: 0.97, y: 0.2 }, { x: 0.87, y: 0.2 }] },
      ])
      setDraft([])
      setTool('select')
      setConfirmed(false)
    }}>Use sample-video calibration</Button>
    <p>Only for the bundled red-light sample: places the line and signal box for you. For other footage, draw your own.</p>
    <div role="toolbar" aria-label="Geometry tools" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
      {tools.map(({ mode, label }) => <Button key={mode} type="button" variant={tool === mode ? 'primary' : 'secondary'} aria-pressed={tool === mode} onClick={() => setTool(mode)}>{label}</Button>)}
      {!!draft.length && <Button type="button" variant="secondary" onClick={() => setDraft([])}>Cancel drawing</Button>}
      {isPolygon && <Button type="button" disabled={draft.length < 3} onClick={() => complete({ kind: 'polygon', points: draft })}>{finishLabel}</Button>}
      <Button type="button" variant="danger" disabled={!geometries.length && !draft.length} onClick={() => { setGeometries([]); setDraft([]); setConfirmed(false) }}>Clear geometry</Button>
    </div>
    <VideoPlayer src={src} fps={fps} ariaLabel="Calibration video">
      <CalibrationCanvas width={sourceWidth} height={sourceHeight} sourceWidth={sourceWidth} sourceHeight={sourceHeight} geometries={geometries} tool={tool} draftPoints={draft} onDraftChange={setDraft} onGeometryComplete={complete} />
    </VideoPlayer>
    <p role="status">Stop line: {hasStopLine ? 'saved' : 'missing'}. ROI, lane, or zone: {hasArea ? 'saved' : 'missing'}.</p>
    {draft.length > 0 && <p role="status">{isPolygon ? `${draft.length} corners — not saved. ${draft.length < 3 ? 'Add at least three corners, then' : 'Click'} ${finishLabel}.` : tool === 'roi' ? 'Rectangle unfinished — click the opposite corner.' : 'Stop line unfinished — click the second point.'}</p>}
    {!canConfirm && !draft.length && <p role="status">Add a stop line and at least one ROI, lane, or zone before confirming.</p>}
    {confirmed && <p role="status">Calibration confirmed.</p>}
    <Button type="button" disabled={!canConfirm || confirmed} onClick={() => { onConfirm(geometries); setConfirmed(true) }}>Confirm calibration</Button>
  </section>
}
