import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { theme } from '../ui/theme'

export interface ChecklistItem {
  id: string
  label: string
}

export interface ChecklistSection {
  title: string
  items: ChecklistItem[]
}

export const CHECKLIST: ChecklistSection[] = [
  {
    title: 'Environment prerequisites',
    items: [
      { id: 'demo-env-footage', label: 'Approved, rights-cleared short clip is available for the red-light demo.' },
      { id: 'demo-env-second-clip', label: 'A second clip from the same calibrated viewpoint is ready for rerun.' },
      { id: 'demo-env-staging', label: 'Staging environment is warmed, budget cap is set, and webhook destination is configured.' },
      { id: 'demo-env-fallback', label: 'Fallback plan is documented for failed provider calls with labeled cached/replay results.' },
      { id: 'demo-env-reviewer', label: 'An independent human reviewer is present for the usability observation.' },
    ],
  },
  {
    title: 'Core demo acceptance',
    items: [
      { id: 'demo-core-create-chat', label: 'A new user lands on the workspace without writing code.' },
      { id: 'demo-core-create-prompt', label: 'The user types an objective such as "Flag vehicles that cross the stop line while the traffic light is red."' },
      { id: 'demo-core-create-interpretation', label: 'The builder agent responds with a typed, plain-language interpretation or focused clarification request.' },
      { id: 'demo-core-create-unsupported', label: 'Unsupported or ambiguous prompts are refused or clarified, not silently accepted.' },
      { id: 'demo-core-create-validated', label: 'Within five minutes a validated AppSpec is visible with title, objective, capability, and evidence policy.' },
      { id: 'demo-core-upload-metadata', label: 'The user uploads a supported short MP4 and source metadata is displayed.' },
      { id: 'demo-core-upload-invalid', label: 'Invalid media is rejected with an actionable message before analysis starts.' },
      { id: 'demo-core-calibrate-propose', label: 'The agent proposes a stop line and governing signal region on the video canvas.' },
      { id: 'demo-core-calibrate-edit', label: 'The user can see, edit, and confirm the proposed geometry.' },
      { id: 'demo-core-calibrate-warnings', label: 'Calibration warnings are shown for ambiguous geometry before confirmation.' },
      { id: 'demo-core-calibrate-revision', label: 'Confirmed calibration is saved with a revision and changing the camera requires new confirmation.' },
      { id: 'demo-core-run-status', label: 'Starting a run shows explicit job status with progress updates.' },
      { id: 'demo-core-run-events', label: 'Event cards appear with source timestamp, rule ID, thumbnail, machine decision, and review status.' },
      { id: 'demo-core-run-evidence', label: 'Selecting a card shows a playable evidence interval and before/at/after frames/crops.' },
      { id: 'demo-core-run-cases', label: 'Positive, negative, and unknown/abstention cases are visible or explainable in results.' },
      { id: 'demo-core-run-reload', label: 'Analysis can be cancelled and does not disappear on reload.' },
      { id: 'demo-core-review-controls', label: 'Each event card exposes controls to confirm, dismiss, or leave unreviewed.' },
      { id: 'demo-core-review-update', label: 'Approved or rejected events update visibly and are reflected in counters/filters.' },
      { id: 'demo-core-action-preview', label: 'A dry-run action preview shows what would be delivered without sending unless opt-in is confirmed.' },
      { id: 'demo-core-refine-version', label: 'A follow-up chat message creates a new app version and a version diff is visible.' },
      { id: 'demo-core-refine-rerun', label: 'Re-running the same clip shows a changed result consistent with the refinement.' },
      { id: 'demo-core-refine-second', label: 'The saved app can process a second clip from the calibrated view without rebuilding.' },
    ],
  },
  {
    title: 'Error and edge-case handling',
    items: [
      { id: 'demo-error-unsupported', label: 'Off-scope prompts such as facial recognition or automatic fines are refused with a clear reason.' },
      { id: 'demo-error-media', label: 'Corrupt, unsupported, or oversized uploads show a human-readable validation message.' },
      { id: 'demo-error-calibration', label: 'Low-confidence or ambiguous geometry surfaces a warning before confirmation.' },
      { id: 'demo-error-budget', label: 'Run creation is blocked when per-run caps, concurrency, or spend limits would be exceeded.' },
      { id: 'demo-error-provider', label: 'Failed provider calls or GPU cold starts report adapter provenance and a retry/cancel path.' },
    ],
  },
  {
    title: 'Accessibility basics',
    items: [
      { id: 'demo-a11y-keyboard', label: 'All interactive controls are reachable and operable via keyboard.' },
      { id: 'demo-a11y-labels', label: 'Checkboxes, buttons, and form fields have descriptive labels or aria-label text.' },
      { id: 'demo-a11y-color', label: 'Decision badges and statuses do not rely on color alone.' },
      { id: 'demo-a11y-canvas', label: 'Video canvas exposes equivalent geometry and calibration metadata in text.' },
    ],
  },
  {
    title: 'Performance basics',
    items: [
      { id: 'demo-perf-load', label: 'Initial app load in the browser is under three seconds on conference Wi-Fi.' },
      { id: 'demo-perf-progress', label: 'Analysis progress updates are visible at least every few seconds.' },
      { id: 'demo-perf-render', label: 'Event cards and thumbnails render without blocking the main thread.' },
    ],
  },
  {
    title: 'Exit criteria',
    items: [
      { id: 'demo-exit-core', label: 'Core demo acceptance items are demonstrated on the real built app.' },
      { id: 'demo-exit-errors', label: 'Error and edge-case items are demonstrated or truthfully labeled as simulated.' },
      { id: 'demo-exit-a11y-perf', label: 'Accessibility and performance basics are validated by observation or recording.' },
      { id: 'demo-exit-second-app', label: 'A second app is created through chat and executed using the same compiler/runtime.' },
      { id: 'demo-exit-no-send', label: 'No unapproved external action or webhook is sent during the demo.' },
      { id: 'demo-exit-cached-label', label: 'Cached, replayed, or synthetic results are clearly labeled with exact revisions.' },
      { id: 'demo-exit-usability', label: 'Independent reviewer confirms the four-of-five usability target or documents blockers.' },
      { id: 'demo-exit-issues', label: 'No critical unresolved security, correctness, or privacy issue remains open.' },
    ],
  },
]

export interface DemoChecklistProps {
  storageKey?: string
}

const readSavedIds = (storageKey: string): Set<string> => {
  if (typeof window === 'undefined') return new Set()
  try {
    const raw = window.localStorage.getItem(storageKey)
    if (!raw) return new Set()
    const parsed = JSON.parse(raw) as unknown
    if (Array.isArray(parsed)) return new Set(parsed.filter((id) => typeof id === 'string'))
  } catch {
    // Ignore corrupt localStorage data; return empty set.
  }
  return new Set()
}

const saveIds = (storageKey: string, ids: Set<string>) => {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(Array.from(ids)))
  } catch {
    // Ignore storage errors (e.g. private mode).
  }
}

export function DemoChecklist({ storageKey = 'r03-demo-checklist' }: DemoChecklistProps) {
  const allIds = useMemo(() => CHECKLIST.flatMap((section) => section.items.map((item) => item.id)), [])

  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => readSavedIds(storageKey))

  useEffect(() => {
    saveIds(storageKey, checkedIds)
  }, [storageKey, checkedIds])

  const toggle = useCallback((id: string) => {
    setCheckedIds((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const checkedCount = checkedIds.size
  const totalCount = allIds.length

  const containerStyle: CSSProperties = {
    fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    color: theme.colors.text,
    backgroundColor: theme.colors.background,
    padding: theme.spacing.lg,
    maxWidth: '800px',
    margin: '0 auto',
  }

  const headerStyle: CSSProperties = {
    marginBottom: theme.spacing.md,
    paddingBottom: theme.spacing.md,
    borderBottom: `1px solid ${theme.colors.surfaceBorder}`,
  }

  const titleStyle: CSSProperties = {
    fontSize: theme.fontSizes.xl,
    fontWeight: 700,
    margin: `0 0 ${theme.spacing.sm} 0`,
  }

  const progressStyle: CSSProperties = {
    fontSize: theme.fontSizes.sm,
    color: theme.colors.textSecondary,
  }

  const sectionStyle: CSSProperties = {
    marginBottom: theme.spacing.lg,
    backgroundColor: theme.colors.surface,
    border: `1px solid ${theme.colors.surfaceBorder}`,
    borderRadius: theme.radii.md,
    padding: theme.spacing.md,
  }

  const sectionTitleStyle: CSSProperties = {
    fontSize: theme.fontSizes.lg,
    fontWeight: 600,
    margin: `0 0 ${theme.spacing.md} 0`,
  }

  const listStyle: CSSProperties = {
    listStyle: 'none',
    margin: 0,
    padding: 0,
  }

  const itemStyle = (checked: boolean): CSSProperties => ({
    display: 'flex',
    alignItems: 'flex-start',
    gap: theme.spacing.sm,
    padding: theme.spacing.sm,
    borderRadius: theme.radii.sm,
    backgroundColor: checked ? theme.colors.background : 'transparent',
    transition: `background-color ${theme.transitions.fast}`,
  })

  const checkboxStyle: CSSProperties = {
    width: '1.125em',
    height: '1.125em',
    flexShrink: 0,
    marginTop: '0.15em',
    cursor: 'pointer',
  }

  const labelStyle: CSSProperties = {
    cursor: 'pointer',
    lineHeight: 1.4,
    fontSize: theme.fontSizes.sm,
  }

  return (
    <section aria-labelledby="demo-checklist-title" style={containerStyle}>
      <header style={headerStyle}>
        <h1 id="demo-checklist-title" style={titleStyle}>
          R03 demo acceptance checklist
        </h1>
        <p style={progressStyle} aria-live="polite" aria-atomic="true">
          {checkedCount} of {totalCount} complete
        </p>
      </header>

      {CHECKLIST.map((section) => (
        <section key={section.title} aria-labelledby={`section-${section.title.replace(/\s+/g, '-')}`} style={sectionStyle}>
          <h2 id={`section-${section.title.replace(/\s+/g, '-')}`} style={sectionTitleStyle}>
            {section.title}
          </h2>
          <ul role="list" style={listStyle}>
            {section.items.map((item) => {
              const checked = checkedIds.has(item.id)
              return (
                <li key={item.id} role="listitem" style={itemStyle(checked)}>
                  <input
                    type="checkbox"
                    id={item.id}
                    data-check-id={item.id}
                    checked={checked}
                    onChange={() => toggle(item.id)}
                    style={checkboxStyle}
                    aria-checked={checked}
                  />
                  <label htmlFor={item.id} style={labelStyle}>
                    {item.label}
                  </label>
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </section>
  )
}
