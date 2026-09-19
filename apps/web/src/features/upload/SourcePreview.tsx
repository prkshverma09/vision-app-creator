export interface SourceMetadata {
  asset_id: string
  status: 'processing' | 'ready' | 'failed' | 'deleted'
  duration_ms?: number
  width?: number
  height?: number
  message?: string
}

export interface SourcePreviewProps {
  url: string
  metadata?: SourceMetadata
}

function formatDuration(durationMs: number) {
  const totalSeconds = Math.floor(durationMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

export function SourcePreview({ url, metadata }: SourcePreviewProps) {
  return (
    <section aria-label="Source preview">
      <video aria-label="Source video preview" src={url} controls preload="metadata" style={{ maxWidth: '100%', display: 'block' }} />
      {metadata?.status === 'ready' && (
        <dl>
          <div><dt>Duration</dt><dd>{metadata.duration_ms === undefined ? 'Unknown' : formatDuration(metadata.duration_ms)}</dd></div>
          <div><dt>Dimensions</dt><dd>{metadata.width !== undefined && metadata.height !== undefined ? `${metadata.width} × ${metadata.height}` : 'Unknown'}</dd></div>
        </dl>
      )}
    </section>
  )
}
