import { theme } from '../../ui'

export type ChatMessageKind = 'user' | 'assistant' | 'clarification' | 'error'

export interface ChatMessage {
  id: string
  kind: ChatMessageKind
  content: string
}

export interface ChatThreadProps {
  messages: ChatMessage[]
  label?: string
}

const labels: Record<ChatMessageKind, string> = {
  user: 'You',
  assistant: 'Assistant',
  clarification: 'Clarification needed',
  error: 'Error',
}

export function ChatThread({ messages, label = 'Conversation' }: ChatThreadProps) {
  return (
    <section aria-label={label}>
      {messages.length === 0 ? (
        <p style={{ color: theme.colors.textSecondary }}>Describe what you want to detect.</p>
      ) : (
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: theme.spacing.md }}>
          {messages.map((message) => (
            <li
              key={message.id}
              data-message-kind={message.kind}
              role={message.kind === 'error' ? 'alert' : undefined}
              style={{
                padding: theme.spacing.md,
                border: `1px solid ${message.kind === 'error' ? theme.colors.error : theme.colors.surfaceBorder}`,
                borderRadius: theme.radii.md,
                background: message.kind === 'user' ? theme.colors.background : theme.colors.surface,
              }}
            >
              <strong>{labels[message.kind]}</strong>
              <p style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>{message.content}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}
