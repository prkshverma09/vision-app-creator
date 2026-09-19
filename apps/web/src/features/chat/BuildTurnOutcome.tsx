import { useEffect, useState, type FormEvent } from 'react'
import type { AppSpec, CompilerOutcome } from '@vision-app/contracts'
import { Button, Card, Input, theme } from '../../ui'

export interface BuildTurnOutcomeProps {
  outcome: CompilerOutcome
  onClarify?: (answers: string[]) => void
  onAccept?: (version: AppSpec) => void
  onEditPrompt?: (prompt: string) => void
}

function isAppSpec(value: unknown): value is AppSpec {
  if (!value || typeof value !== 'object') return false
  const kind = (value as { kind?: unknown }).kind
  return kind === 'tracked_rules' || kind === 'semantic_windows'
}

export function BuildTurnOutcome({ outcome, onClarify, onAccept, onEditPrompt }: BuildTurnOutcomeProps) {
  if (outcome.kind === 'needs_input') {
    return <ClarificationForm questions={outcome.questions} onSubmit={onClarify} />
  }
  if (outcome.kind === 'unsupported_request') {
    return (
      <Card>
        <div role="alert">
          <strong>Request not supported</strong>
          <p>{outcome.reason}</p>
          <code>{outcome.code}</code>
        </div>
      </Card>
    )
  }
  if (!isAppSpec(outcome.version)) {
    return <div role="alert">The proposed version could not be displayed.</div>
  }
  return <Proposal version={outcome.version} onAccept={onAccept} onEditPrompt={onEditPrompt} />
}

function ClarificationForm({ questions, onSubmit }: { questions: string[]; onSubmit?: (answers: string[]) => void }) {
  const [answers, setAnswers] = useState(() => questions.map(() => ''))
  useEffect(() => setAnswers(questions.map(() => '')), [questions])
  const complete = answers.every((answer) => answer.trim().length > 0)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (complete) onSubmit?.(answers.map((answer) => answer.trim()))
  }

  return (
    <Card>
      <form onSubmit={submit} aria-label="Clarification questions" style={{ display: 'grid', gap: theme.spacing.md }}>
        <strong>More information needed</strong>
        {questions.map((question, index) => (
          <Input
            key={`${index}-${question}`}
            label={question}
            value={answers[index]}
            onChange={(event) => setAnswers((current) => current.map((answer, answerIndex) => answerIndex === index ? event.target.value : answer))}
          />
        ))}
        <Button type="submit" disabled={!complete}>Submit clarification</Button>
      </form>
    </Card>
  )
}

function Proposal({ version, onAccept, onEditPrompt }: { version: AppSpec; onAccept?: (version: AppSpec) => void; onEditPrompt?: (prompt: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [prompt, setPrompt] = useState('')
  const detail = version.kind === 'tracked_rules'
    ? `${version.rules.length} tracking rule${version.rules.length === 1 ? '' : 's'}`
    : `${version.conditions.length} semantic condition${version.conditions.length === 1 ? '' : 's'}`

  return (
    <Card>
      <article aria-label="Proposed version">
        <p><strong>Proposal ready for review</strong></p>
        <h2>{version.title}</h2>
        <p>{version.objective}</p>
        <p>{detail}</p>
        <div style={{ display: 'flex', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
          <Button type="button" onClick={() => onAccept?.(version)}>Accept proposal</Button>
          <Button type="button" variant="secondary" onClick={() => setEditing((value) => !value)}>Edit prompt</Button>
        </div>
        {editing && (
          <form onSubmit={(event) => { event.preventDefault(); if (prompt.trim()) onEditPrompt?.(prompt.trim()) }} style={{ marginTop: theme.spacing.md }}>
            <Input label="Revision request" value={prompt} onChange={(event) => setPrompt(event.target.value)} />
            <Button type="submit" disabled={!prompt.trim()}>Send revision</Button>
          </form>
        )}
      </article>
    </Card>
  )
}
