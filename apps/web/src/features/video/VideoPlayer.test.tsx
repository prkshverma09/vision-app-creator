import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { VideoPlayer } from './VideoPlayer'

describe('VideoPlayer', () => {
  it('uses a WebM preview for backend media instead of requiring MP4 codecs', () => {
    const { rerender } = render(<VideoPlayer src="/api/v1/media/source-1" />)
    expect(screen.getByLabelText('Video preview')).toHaveAttribute('src', '/api/v1/media/source-1/preview.webm')
    rerender(<VideoPlayer src="blob:local-preview" />)
    expect(screen.getByLabelText('Video preview')).toHaveAttribute('src', 'blob:local-preview')
  })

  it('reports decode errors accurately and clears the error for a new source', () => {
    const { rerender } = render(<VideoPlayer src="/api/v1/media/source-1" />)
    const video = screen.getByLabelText('Video preview')
    Object.defineProperty(video, 'error', { value: { code: 4, message: 'no supported streams' } })
    fireEvent.error(video)
    expect(screen.getByRole('alert')).toHaveTextContent('no supported streams')
    expect(screen.getByRole('alert')).not.toHaveTextContent('expired')
    rerender(<VideoPlayer src="/api/v1/media/source-2" />)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('seeks with the scrubber and frame-step controls', () => {
    render(<VideoPlayer src="fixture.mp4" fps={25} ariaLabel="Scene video" />)
    const video = screen.getByLabelText('Scene video') as HTMLVideoElement
    Object.defineProperty(video, 'duration', { value: 10, configurable: true })
    fireEvent.loadedMetadata(video)
    fireEvent.change(screen.getByLabelText('Video position'), { target: { value: '4' } })
    expect(video.currentTime).toBe(4)
    fireEvent.click(screen.getByRole('button', { name: 'Next frame' }))
    expect(video.currentTime).toBeCloseTo(4.04)
    fireEvent.click(screen.getByRole('button', { name: 'Previous frame' }))
    expect(video.currentTime).toBeCloseTo(4)
  })
})
