import { useEffect, useRef, useState } from 'react'
import type { ApiClient } from '../../client'
import { Button } from '../../ui'
import { SourcePreview, type SourceMetadata } from './SourcePreview'

export const MAX_UPLOAD_BYTES = 250_000_000

type UploadState = 'empty' | 'uploading' | 'validating' | 'ready' | 'error' | 'cancelled'

export interface UploadGrant {
  upload_id: string
  upload_url: string
  headers?: Record<string, string>
}

export type DirectUploader = (
  grant: UploadGrant,
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
) => Promise<void>

export interface UploadPanelProps {
  apiClient: ApiClient
  onReady?: (source: SourceMetadata) => void
  uploader?: DirectUploader
  pollIntervalMs?: number
  maxBytes?: number
}

export const uploadWithProgress: DirectUploader = (grant, file, onProgress, signal) => new Promise((resolve, reject) => {
  const request = new XMLHttpRequest()
  request.open('PUT', grant.upload_url)
  Object.entries(grant.headers ?? {}).forEach(([name, value]) => request.setRequestHeader(name, value))
  request.upload.onprogress = (event) => {
    if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
  }
  request.onload = () => request.status >= 200 && request.status < 300
    ? resolve()
    : reject(new Error(`Byte upload failed (${request.status})`))
  request.onerror = () => reject(new Error('Byte upload failed. Check your connection and retry.'))
  request.onabort = () => reject(new DOMException('Upload cancelled', 'AbortError'))
  signal?.addEventListener('abort', () => request.abort(), { once: true })
  request.send(file)
})

const delay = (milliseconds: number, signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  const timer = setTimeout(resolve, milliseconds)
  signal.addEventListener('abort', () => {
    clearTimeout(timer)
    reject(new DOMException('Upload cancelled', 'AbortError'))
  }, { once: true })
})

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Upload failed. Please retry.'
}

export function UploadPanel({ apiClient, onReady, uploader = uploadWithProgress, pollIntervalMs = 500, maxBytes = MAX_UPLOAD_BYTES }: UploadPanelProps) {
  const [file, setFile] = useState<File>()
  const [previewUrl, setPreviewUrl] = useState('')
  const [state, setState] = useState<UploadState>('empty')
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [metadata, setMetadata] = useState<SourceMetadata>()
  const abortRef = useRef<AbortController | undefined>(undefined)
  const busyRef = useRef(false)

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => () => {
    if (previewUrl && typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(previewUrl)
  }, [previewUrl])

  async function beginUpload(selectedFile: File) {
    if (busyRef.current) return
    if (selectedFile.size > maxBytes) {
      setFile(selectedFile)
      setError(`Video must be ${maxBytes / 1_000_000} MB or smaller.`)
      setState('error')
      return
    }
    if (selectedFile.type !== 'video/mp4') {
      setFile(selectedFile)
      setError('Choose an MP4 video file.')
      setState('error')
      return
    }

    busyRef.current = true
    const controller = new AbortController()
    abortRef.current = controller
    setFile(selectedFile)
    setError('')
    setMetadata(undefined)
    setProgress(0)
    setState('uploading')
    setPreviewUrl((current) => {
      if (current) URL.revokeObjectURL(current)
      return URL.createObjectURL(selectedFile)
    })

    try {
      const grant = await apiClient.post<UploadGrant>('/v1/uploads', {
        filename: selectedFile.name,
        content_type: selectedFile.type,
        size_bytes: selectedFile.size,
      }, { idempotencyKey: crypto.randomUUID(), signal: controller.signal })
      await uploader(grant, selectedFile, setProgress, controller.signal)
      setState('validating')
      let source = await apiClient.post<SourceMetadata>(`/v1/uploads/${grant.upload_id}/complete`, {}, { signal: controller.signal })
      while (source.status === 'processing') {
        await delay(pollIntervalMs, controller.signal)
        source = await apiClient.get<SourceMetadata>(`/v1/assets/${source.asset_id}`, { signal: controller.signal })
      }
      if (source.status === 'deleted') throw new Error('This source was deleted and is no longer available.')
      if (source.status === 'failed') throw new Error(source.message ?? 'The video could not be validated.')
      if (source.status !== 'ready') throw new Error('The video did not reach a ready state.')
      setMetadata(source)
      setState('ready')
      onReady?.(source)
    } catch (caught) {
      if (controller.signal.aborted) {
        setState('cancelled')
      } else {
        setError(errorMessage(caught))
        setState('error')
      }
    } finally {
      busyRef.current = false
    }
  }

  function selectFile(selectedFile?: File) {
    if (selectedFile) void beginUpload(selectedFile)
  }

  return (
    <section aria-labelledby="upload-heading">
      <h2 id="upload-heading">Upload source video</h2>
      <label style={{ display: 'block', padding: 24, border: '2px dashed currentColor', cursor: 'pointer' }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => { event.preventDefault(); selectFile(event.dataTransfer.files[0]) }}>
        Choose an MP4 video or drop it here
        <input type="file" accept="video/mp4,.mp4" onChange={(event) => selectFile(event.target.files?.[0])} style={{ display: 'block' }} />
      </label>
      <p>Maximum size: {maxBytes / 1_000_000} MB</p>

      {state === 'uploading' && <div aria-live="polite"><p>Uploading {file?.name}</p><progress aria-label="Upload progress" aria-valuenow={progress} value={progress} max={100}>{progress}%</progress></div>}
      {state === 'validating' && <p role="status" aria-live="polite">Validating video…</p>}
      {state === 'ready' && <p role="status">Source ready</p>}
      {state === 'cancelled' && <p role="status">Upload cancelled</p>}
      {error && <p role="alert">{error}</p>}

      {(state === 'uploading' || state === 'validating') && <Button type="button" variant="secondary" onClick={() => abortRef.current?.abort()}>Cancel upload</Button>}
      {(state === 'error' || state === 'cancelled') && file && file.size <= maxBytes && <Button type="button" onClick={() => void beginUpload(file)}>Retry upload</Button>}
      {previewUrl && <SourcePreview url={previewUrl} metadata={metadata} />}
    </section>
  )
}
