import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DemoChecklist } from './DemoChecklist'

const STORAGE_KEY = 'r03-demo-checklist'

describe('DemoChecklist', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders the checklist title and sections', () => {
    render(<DemoChecklist />)

    expect(screen.getByRole('heading', { name: /R03 demo acceptance checklist/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Core demo acceptance/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Error and edge-case handling/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Accessibility basics/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Performance basics/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Exit criteria/i })).toBeInTheDocument()
  })

  it('renders a checkbox for every checklist item', () => {
    render(<DemoChecklist />)

    const checkboxes = screen.getAllByRole('checkbox')
    expect(checkboxes.length).toBeGreaterThan(20)
    checkboxes.forEach((checkbox) => {
      expect(checkbox).not.toBeChecked()
    })
  })

  it('toggles a checklist item when its checkbox is clicked', async () => {
    const user = userEvent.setup()
    render(<DemoChecklist />)

    const first = screen.getAllByRole('checkbox')[0]
    expect(first).not.toBeChecked()

    await user.click(first)
    expect(first).toBeChecked()

    await user.click(first)
    expect(first).not.toBeChecked()
  })

  it('toggles a checklist item when its label is clicked', async () => {
    const user = userEvent.setup()
    render(<DemoChecklist />)

    const firstCheckbox = screen.getAllByRole('checkbox')[0]
    const firstLabel = screen.getAllByRole('listitem')[0].querySelector('label')
    if (!firstLabel) throw new Error('Expected checklist item label')

    await user.click(firstLabel)
    expect(firstCheckbox).toBeChecked()

    await user.click(firstLabel)
    expect(firstCheckbox).not.toBeChecked()
  })

  it('labels every checkbox with its checklist item text', () => {
    render(<DemoChecklist />)

    expect(
      screen.getByRole('checkbox', { name: /new user lands on the workspace without writing code/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /uploads a supported short mp4/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('checkbox', { name: /rejected with an actionable message/i }),
    ).toBeInTheDocument()
  })

  it('persists checked state to localStorage', async () => {
    const user = userEvent.setup()
    render(<DemoChecklist />)

    const checkboxes = screen.getAllByRole('checkbox')
    await user.click(checkboxes[0])
    await user.click(checkboxes[2])

    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
    expect(saved).toHaveLength(2)
  })

  it('restores checked state from localStorage on mount', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['demo-env-footage', 'demo-core-upload-metadata']))

    render(<DemoChecklist />)

    const checkboxes = screen.getAllByRole('checkbox')
    const ids = checkboxes.map((cb) => cb.getAttribute('data-check-id'))
    expect(checkboxes[ids.indexOf('demo-env-footage')]).toBeChecked()
    expect(checkboxes[ids.indexOf('demo-core-upload-metadata')]).toBeChecked()
    expect(checkboxes[ids.indexOf('demo-core-upload-invalid')]).not.toBeChecked()
  })

  it('reflects progress as the number of checked items', async () => {
    const user = userEvent.setup()
    render(<DemoChecklist />)

    const checkboxes = screen.getAllByRole('checkbox')
    const progressBefore = screen.getByText(/\d+ of \d+ complete/i)
    const beforeMatch = progressBefore.textContent?.match(/(\d+) of \d+ complete/)
    const beforeCount = Number(beforeMatch?.[1] ?? 0)

    await user.click(checkboxes[0])

    const progressAfter = screen.getByText(/\d+ of \d+ complete/i)
    const afterMatch = progressAfter.textContent?.match(/(\d+) of \d+ complete/)
    const afterCount = Number(afterMatch?.[1] ?? 0)

    expect(afterCount).toBe(beforeCount + 1)
  })

  it('does not make backend or API calls', () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    render(<DemoChecklist />)
    expect(fetchSpy).not.toHaveBeenCalled()
    fetchSpy.mockRestore()
  })
})
