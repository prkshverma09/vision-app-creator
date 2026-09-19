import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ChatInput } from './ChatInput'
import { ChatThread } from './ChatThread'
import { BuildTurnOutcome } from './BuildTurnOutcome'
import { needsInput, proposedVersion, unsupportedRequest } from './test-fixtures'

describe('ChatThread', () => {
  it('renders user, assistant, clarification, and error messages as data', () => {
    render(<ChatThread messages={[
      { id: '1', kind: 'user', content: 'Watch <script>alert(1)</script>' },
      { id: '2', kind: 'assistant', content: 'I can help configure that.' },
      { id: '3', kind: 'clarification', content: 'Which lane?' },
      { id: '4', kind: 'error', content: 'Build timed out.' },
    ]} />)

    expect(screen.getByText('Watch <script>alert(1)</script>')).toBeInTheDocument()
    expect(screen.getByText('I can help configure that.')).toBeInTheDocument()
    expect(screen.getByText('Which lane?')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Build timed out.')
    expect(document.querySelector('script')).not.toBeInTheDocument()
  })
})

describe('ChatInput', () => {
  it('submits text, clears the draft, and prevents empty sends', async () => {
    const user = userEvent.setup()
    const onSubmit = vi.fn()
    render(<ChatInput onSubmit={onSubmit} />)

    const input = screen.getByRole('textbox', { name: 'Message' })
    await user.type(input, 'Ignore motorcycles')
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(onSubmit).toHaveBeenCalledWith('Ignore motorcycles')
    expect(input).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})

describe('BuildTurnOutcome', () => {
  it('renders clarification questions and submits answers', async () => {
    const user = userEvent.setup()
    const onClarify = vi.fn()
    render(<BuildTurnOutcome outcome={needsInput} onClarify={onClarify} />)

    expect(screen.queryByText(/ready to run/i)).not.toBeInTheDocument()
    const answer = screen.getByLabelText('Which signal governs this lane?')
    await user.type(answer, 'The signal on the left')
    await user.click(screen.getByRole('button', { name: 'Submit clarification' }))
    expect(onClarify).toHaveBeenCalledWith(['The signal on the left'])
  })

  it('displays unsupported requests without success actions', () => {
    render(<BuildTurnOutcome outcome={unsupportedRequest} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Identity recognition is excluded')
    expect(screen.getByText('unsupported_capability')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /accept/i })).not.toBeInTheDocument()
  })

  it('shows a proposal summary and accepts the proposal explicitly', async () => {
    const user = userEvent.setup()
    const onAccept = vi.fn()
    const onEditPrompt = vi.fn()
    render(<BuildTurnOutcome outcome={proposedVersion} onAccept={onAccept} onEditPrompt={onEditPrompt} />)

    expect(screen.getByRole('heading', { name: 'Red light crossing' })).toBeInTheDocument()
    expect(screen.getByText('Detect vehicles crossing during a red signal')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Accept proposal' }))
    expect(onAccept).toHaveBeenCalledWith(proposedVersion.version)
  })
})
