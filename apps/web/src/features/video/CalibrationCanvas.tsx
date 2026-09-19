import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import type { BoxN, PointN } from '@vision-app/contracts'
import { displayToNormalized, normalizedToDisplay } from './geometry'

export type GeometryTool = 'select' | 'stop-line' | 'roi' | 'lane-zone'
export type OverlayGeometry =
  | { id: string; kind: 'point'; point: PointN; label?: string }
  | { id: string; kind: 'box'; box: BoxN; label?: string }
  | { id: string; kind: 'line' | 'polygon'; points: PointN[]; label?: string }
export type CompletedGeometry = { kind: 'line' | 'polygon'; points: PointN[] }

interface Props {
  width: number
  height: number
  sourceWidth: number
  sourceHeight: number
  geometries: OverlayGeometry[]
  tool?: GeometryTool
  draftPoints?: PointN[]
  onDraftChange?: (points: PointN[]) => void
  onGeometryComplete?: (geometry: CompletedGeometry) => void
}

function rectangle(a: PointN, b: PointN): PointN[] {
  const left = Math.min(a.x, b.x), right = Math.max(a.x, b.x)
  const top = Math.min(a.y, b.y), bottom = Math.max(a.y, b.y)
  return [{ x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }]
}

export function CalibrationCanvas({ width, height, sourceWidth, sourceHeight, geometries, tool = 'select', draftPoints, onDraftChange, onGeometryComplete }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const press = useRef<{ point: PointN; x: number; y: number } | null>(null)
  const skipClick = useRef(false)
  const [hover, setHover] = useState<PointN | null>(null)
  const [localDraft, setLocalDraft] = useState<PointN[]>([])
  const draft = draftPoints ?? localDraft
  const setDraft = onDraftChange ?? setLocalDraft
  const transform = { sourceWidth, sourceHeight, displayWidth: width, displayHeight: height }

  useEffect(() => {
    setDraft([])
    setHover(null)
    press.current = null
    skipClick.current = false
  }, [tool])
  useEffect(() => {
    const context = canvasRef.current?.getContext('2d')
    if (!context) return
    context.clearRect(0, 0, width, height)
    context.lineWidth = 2
    context.strokeStyle = '#22d3ee'
    context.fillStyle = 'rgba(34, 211, 238, .18)'
    const path = (points: PointN[], close: boolean) => {
      if (!points.length) return
      context.beginPath()
      const first = normalizedToDisplay(points[0], transform)
      context.moveTo(first.x, first.y)
      points.slice(1).forEach((point) => { const p = normalizedToDisplay(point, transform); context.lineTo(p.x, p.y) })
      if (close) { context.closePath(); context.fill() }
      context.stroke()
    }
    geometries.forEach((geometry) => {
      if (geometry.kind === 'point') {
        const point = normalizedToDisplay(geometry.point, transform)
        context.beginPath(); context.arc(point.x, point.y, 5, 0, Math.PI * 2); context.fill(); context.stroke()
      } else if (geometry.kind === 'box') {
        const start = normalizedToDisplay({ x: geometry.box.x1, y: geometry.box.y1 }, transform)
        const end = normalizedToDisplay({ x: geometry.box.x2, y: geometry.box.y2 }, transform)
        context.strokeRect(start.x, start.y, end.x - start.x, end.y - start.y)
      } else path(geometry.points, geometry.kind === 'polygon')
    })
    const start = press.current?.point ?? draft[0]
    context.setLineDash([6, 4])
    if (start && hover && tool === 'roi') path(rectangle(start, hover), true)
    else if (start && hover && tool === 'stop-line') path([start, hover], false)
    else path(draft, false)
    context.setLineDash([])
    if (start) {
      const point = normalizedToDisplay(start, transform)
      context.beginPath(); context.arc(point.x, point.y, 4, 0, Math.PI * 2); context.fill(); context.stroke()
    }
  }, [draft, geometries, height, hover, sourceHeight, sourceWidth, tool, width])

  const pointFromEvent = (event: MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return displayToNormalized({ x: (event.clientX - rect.left) * width / rect.width, y: (event.clientY - rect.top) * height / rect.height }, transform)
  }
  const completePair = (a: PointN, b: PointN) => {
    if (a.x === b.x && a.y === b.y) return
    if (tool === 'roi' && (a.x === b.x || a.y === b.y)) return
    const points = tool === 'roi' ? rectangle(a, b) : [a, b].sort((p, q) => p.y - q.y || p.x - q.x)
    onGeometryComplete?.({ kind: tool === 'roi' ? 'polygon' : 'line', points })
    setDraft([])
    setHover(null)
  }
  const addPoint = (event: MouseEvent<HTMLCanvasElement>) => {
    if (skipClick.current) { skipClick.current = false; return }
    if (tool === 'select') return
    if (tool === 'lane-zone' && event.detail > 1) return
    const point = pointFromEvent(event)
    if (draft.some(existing => existing.x === point.x && existing.y === point.y)) return
    if (tool !== 'lane-zone' && draft.length) completePair(draft[0], point)
    else setDraft([...draft, point])
  }
  const startDrag = (event: PointerEvent<HTMLCanvasElement>) => {
    if ((tool !== 'stop-line' && tool !== 'roi') || event.button !== 0) return
    skipClick.current = false
    press.current = { point: pointFromEvent(event), x: event.clientX, y: event.clientY }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }
  const endDrag = (event: PointerEvent<HTMLCanvasElement>) => {
    const start = press.current
    press.current = null
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    if (!start || Math.hypot(event.clientX - start.x, event.clientY - start.y) < 4) return
    skipClick.current = true
    completePair(start.point, pointFromEvent(event))
  }
  const finishPolygon = (event: MouseEvent<HTMLCanvasElement>) => {
    if (tool !== 'lane-zone') return
    event.preventDefault()
    if (draft.length < 3) return
    onGeometryComplete?.({ kind: 'polygon', points: draft })
    setDraft([])
  }

  return <canvas ref={canvasRef} width={width} height={height} aria-label="Calibration drawing canvas" onClick={addPoint} onDoubleClick={finishPolygon}
    onPointerDown={startDrag} onPointerMove={(event) => { if (tool !== 'select') setHover(pointFromEvent(event)) }} onPointerUp={endDrag}
    onPointerCancel={() => { press.current = null; setHover(null); setDraft([]) }} onPointerLeave={() => { if (!press.current) setHover(null) }}
    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', touchAction: 'none', pointerEvents: tool === 'select' ? 'none' : 'auto', cursor: tool === 'select' ? 'default' : 'crosshair' }} />
}
