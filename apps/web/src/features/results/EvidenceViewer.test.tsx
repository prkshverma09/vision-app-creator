import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { EvidenceManifest } from '@vision-app/contracts'
import { EvidenceViewer } from './EvidenceViewer'

function makeEvidence(overrides: Partial<EvidenceManifest> = {}): EvidenceManifest {
  return {
    requested_range: { start_ms: 9000, end_ms: 18000 },
    actual_range: { start_ms: 9000, end_ms: 18000 },
    clip_ref: 'clip-1',
    thumbnail_ref: 'thumb-1',
    clipped_start: false,
    clipped_end: false,
    state: 'available',
    ...overrides,
  }
}

describe('EvidenceViewer', () => {
  it('renders a thumbnail image when available', () => {
    render(<EvidenceViewer evidence={makeEvidence()} onSeekToSourceTime={vi.fn()} />)

    const img = screen.getByAltText(/evidence/i)
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('src', expect.stringContaining('thumb-1'))
  })

  it('renders a video clip placeholder when clip is available', () => {
    render(<EvidenceViewer evidence={makeEvidence()} onSeekToSourceTime={vi.fn()} />)

    expect(screen.getByText(/clip clip-1/i)).toBeInTheDocument()
  })

  it('displays source-time bounds for actual range', () => {
    render(<EvidenceViewer evidence={makeEvidence()} onSeekToSourceTime={vi.fn()} />)

    expect(screen.getByText(/Actual: 9\.0s/)).toBeInTheDocument()
    expect(screen.getByText(/Actual:.*18\.0s/)).toBeInTheDocument()
  })

  it('calls onSeekToSourceTime when clicking a thumbnail', async () => {
    const user = userEvent.setup()
    const onSeek = vi.fn()
    render(<EvidenceViewer evidence={makeEvidence()} onSeekToSourceTime={onSeek} />)

    await user.click(screen.getByAltText(/evidence/i))
    expect(onSeek).toHaveBeenCalledWith(13500)
  })

  it('shows pending state when evidence is not yet ready', () => {
    render(
      <EvidenceViewer
        evidence={makeEvidence({ state: 'pending', actual_range: null, clip_ref: null, thumbnail_ref: null })}
        onSeekToSourceTime={vi.fn()}
      />
    )

    expect(screen.getByText(/evidence pending/i)).toBeInTheDocument()
  })

  it('shows clipped boundaries notice when range was truncated', () => {
    render(
      <EvidenceViewer
        evidence={makeEvidence({ clipped_start: true, clipped_end: true })}
        onSeekToSourceTime={vi.fn()}
      />
    )

    expect(screen.getByText(/clipped at start/i)).toBeInTheDocument()
    expect(screen.getByText(/clipped at end/i)).toBeInTheDocument()
  })

  it('shows failed state when evidence extraction failed', () => {
    render(
      <EvidenceViewer
        evidence={makeEvidence({ state: 'failed', actual_range: null, clip_ref: null, thumbnail_ref: null })}
        onSeekToSourceTime={vi.fn()}
      />
    )

    expect(screen.getByText(/evidence unavailable/i)).toBeInTheDocument()
  })
})
