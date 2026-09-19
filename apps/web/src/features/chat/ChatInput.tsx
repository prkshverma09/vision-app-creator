import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { Button, theme } from '../../ui'

export interface ChatInputProps {
  onSubmit: (message: string) => void | boolean | Promise<void | boolean>
  disabled?: boolean
  pending?: boolean
  submitDisabled?: boolean
  initialValue?: string
}

export function ChatInput({ onSubmit, disabled = false, pending = false, submitDisabled = false, initialValue = '' }: ChatInputProps) {
  const [draft, setDraft] = useState(initialValue)
  const canSend = draft.trim().length > 0 && !disabled && !pending && !submitDisabled

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSend) return
    const message = draft.trim()
    const accepted = await onSubmit(message)
    if (accepted !== false) setDraft('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  return (
    <form onSubmit={submit} aria-label="Send a message" style={{ display: 'grid', gap: theme.spacing.sm }}>
      <label htmlFor="chat-message" style={{ fontWeight: 500 }}>Message</label>
      <textarea
        id="chat-message"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled || pending}
        rows={3}
        style={{ padding: theme.spacing.sm, borderRadius: theme.radii.md, border: `1px solid ${theme.colors.surfaceBorder}`, resize: 'vertical' }}
      />
      <Button type="submit" disabled={!canSend}>{pending ? 'Sending…' : 'Send'}</Button>
    </form>
  )
}
