import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../../client'
import { MAX_UPLOAD_BYTES, UploadPanel, type DirectUploader } from './UploadPanel'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function videoFile(size = 1024) {
  return new File([new Uint8Array(size)], 'crossing.mp4', { type: 'video/mp4' })
}

describe('UploadPanel', () => {
  const fetchMock = vi.fn<typeof fetch>()
  const apiClient = createApiClient({ getToken: async () => 'test-token' })

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:fixture-video'),
      revokeObjectURL: vi.fn(),
    })
  })

  afterEach(() => vi.unstubAllGlobals())

  it('rejects a file over the exact 250,000,000 byte limit before calling the API', async () => {
    const oversized = videoFile(MAX_UPLOAD_BYTES + 1)
    render(<UploadPanel apiClient={apiClient} />)

    await userEvent.upload(screen.getByLabelText(/choose an mp4 video/i), oversized)

    expect(await screen.findByRole('alert')).toHaveTextContent('250 MB or smaller')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('honors the runtime byte limit instead of the default upload limit', async () => {
    render(<UploadPanel apiClient={apiClient} maxBytes={1_000_000} />)
    expect(screen.getByText('Maximum size: 1 MB')).toBeInTheDocument()
    await userEvent.upload(screen.getByLabelText(/choose an mp4 video/i), videoFile(1_000_001))
    expect(await screen.findByRole('alert')).toHaveTextContent('1 MB or smaller')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows direct upload progress and waits for backend validation before becoming ready', async () => {
    let releaseUpload!: () => void
    let releaseValidation!: (response: Response) => void
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ upload_id: 'upload-1', upload_url: 'https://upload.test/object', headers: {} }, 202))
      .mockResolvedValueOnce(jsonResponse({ asset_id: 'asset-1', status: 'processing' }, 202))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { releaseValidation = resolve }))
    const uploader: DirectUploader = vi.fn(async (_grant, _file, onProgress) => {
      onProgress(40)
      await new Promise<void>((resolve) => { releaseUpload = resolve })
      onProgress(100)
    })
    const onReady = vi.fn()
    render(<UploadPanel apiClient={apiClient} uploader={uploader} pollIntervalMs={0} onReady={onReady} />)

    await userEvent.upload(screen.getByLabelText(/choose an mp4 video/i), videoFile())

    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect(screen.queryByText(/source ready/i)).not.toBeInTheDocument()
    releaseUpload()
    expect(await screen.findByText(/validating video/i)).toBeInTheDocument()
    releaseValidation(jsonResponse({ asset_id: 'asset-1', status: 'ready', duration_ms: 12_500, width: 1920, height: 1080 }))
    expect(await screen.findByText(/source ready/i)).toBeInTheDocument()
    expect(onReady).toHaveBeenCalledWith(expect.objectContaining({ asset_id: 'asset-1' }))
  })

  it('displays the local preview and validated video metadata', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ upload_id: 'upload-1', upload_url: 'https://upload.test/object' }, 202))
      .mockResolvedValueOnce(jsonResponse({ asset_id: 'asset-1', status: 'ready', duration_ms: 65_000, width: 1280, height: 720 }))
    const uploader: DirectUploader = vi.fn(async (_grant, _file, onProgress) => onProgress(100))
    render(<UploadPanel apiClient={apiClient} uploader={uploader} pollIntervalMs={0} />)

    await userEvent.upload(screen.getByLabelText(/choose an mp4 video/i), videoFile())

    expect(await screen.findByText('1:05')).toBeInTheDocument()
    expect(screen.getByText('1280 × 720')).toBeInTheDocument()
    expect(screen.getByLabelText(/source video preview/i)).toHaveAttribute('src', 'blob:fixture-video')
  })

  it('shows an actionable backend error and retries without duplicate automatic initiation', async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ code: 'invalid_media', message: 'The video is corrupt.', field_errors: {}, request_id: 'req-1', retryable: true }, 422))
      .mockResolvedValueOnce(jsonResponse({ upload_id: 'upload-2', upload_url: 'https://upload.test/object' }, 202))
      .mockResolvedValueOnce(jsonResponse({ asset_id: 'asset-2', status: 'ready', duration_ms: 2_000, width: 640, height: 360 }))
    const uploader: DirectUploader = vi.fn(async (_grant, _file, onProgress) => onProgress(100))
    render(<UploadPanel apiClient={apiClient} uploader={uploader} pollIntervalMs={0} />)

    await userEvent.upload(screen.getByLabelText(/choose an mp4 video/i), videoFile())
    expect(await screen.findByRole('alert')).toHaveTextContent('The video is corrupt.')
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole('button', { name: /retry upload/i }))
    await waitFor(() => expect(screen.getByText(/source ready/i)).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})
