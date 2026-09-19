import { useEffect, useRef, useState, type ReactNode } from 'react'

export interface VideoPlayerProps {
  src: string
  fps?: number
  ariaLabel?: string
  poster?: string
  children?: ReactNode
  onTimeChange?: (timeSeconds: number) => void
}

export function VideoPlayer({ src, fps = 30, ariaLabel = 'Video preview', poster, children, onTimeChange }: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [duration, setDuration] = useState(0)
  const [time, setTime] = useState(0)
  const [loadError, setLoadError] = useState('')
  const [playing, setPlaying] = useState(false)
  const playbackSrc = /^\/api\/v1\/media\/[^/?]+$/.test(src) ? `${src}/preview.webm` : src

  useEffect(() => {
    setLoadError('')
    setDuration(0)
    setTime(0)
    setPlaying(false)
  }, [src])

  const seek = (next: number) => {
    const video = videoRef.current
    if (!video) return
    const bounded = Math.min(Number.isFinite(video.duration) ? video.duration : next, Math.max(0, next))
    video.currentTime = bounded
    setTime(bounded)
    onTimeChange?.(bounded)
  }

  return <div>
    <div style={{ position: 'relative', background: '#000', lineHeight: 0 }}>
      <video
        ref={videoRef}
        key={playbackSrc}
        src={playbackSrc}
        preload="auto"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        poster={poster}
        aria-label={ariaLabel}
        controls
        playsInline
        style={{ display: 'block', width: '100%', height: 'auto' }}
        onLoadedMetadata={(event) => {
          setLoadError('')
          setDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0)
        }}
        onError={(event) => {
          const mediaError = event.currentTarget.error
          const reason = mediaError
            ? `code ${mediaError.code}: ${mediaError.message || 'failed to load video'}`
            : 'failed to load video'
          setLoadError(reason)
        }}
        onTimeUpdate={(event) => {
          setTime(event.currentTarget.currentTime)
          onTimeChange?.(event.currentTarget.currentTime)
        }}
      />
      {children}
    </div>
    {loadError && (
      <p role="alert" style={{ color: '#b91c1c', marginTop: 8 }}>
        Video could not be loaded ({loadError}). Playback requires a decodable preview; check the media request or retry the upload.
      </p>
    )}
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
      <button type="button" aria-label={playing ? 'Pause video' : 'Play video'} disabled={!duration || !!loadError} onClick={() => {
        const video = videoRef.current
        if (!video) return
        if (video.paused) void video.play().catch((error: Error) => setLoadError(error.message))
        else video.pause()
      }}>{playing ? 'Pause' : 'Play'}</button>
      <button type="button" aria-label="Previous frame" onClick={() => seek(time - 1 / fps)}>−1 frame</button>
      <input aria-label="Video position" type="range" min={0} max={duration || 0} step="any" value={Math.min(time, duration || 0)} onChange={(event) => seek(Number(event.currentTarget.value))} style={{ flex: 1 }} />
      <button type="button" aria-label="Next frame" onClick={() => seek(time + 1 / fps)}>+1 frame</button>
      <output aria-live="off">{time.toFixed(2)}s</output>
    </div>
  </div>
}
