import type { AppSpec, CompilerOutcome, TrackedRulesSpec } from '@vision-app/contracts'

export const needsInput = {
  kind: 'needs_input',
  questions: ['Which signal governs this lane?'],
} satisfies CompilerOutcome

export const unsupportedRequest = {
  kind: 'unsupported_request',
  code: 'unsupported_capability',
  reason: 'Identity recognition is excluded',
} satisfies CompilerOutcome

export const trackedRulesSpec: TrackedRulesSpec = {
  kind: 'tracked_rules',
  schema_version: '1.0',
  title: 'Red light crossing',
  objective: 'Detect vehicles crossing during a red signal',
  evidence_policy: { before_ms: 3000, after_ms: 3000 },
  approved_action_refs: [],
  limits: { max_duration_ms: 300000, max_model_calls: 10 },
  rules: [{
    rule_id: 'red-crossing',
    capability_id: 'tracked.red_phase_crossing',
    object_classes: ['car', 'truck'],
  }],
}

export const proposedVersion = {
  kind: 'proposed_version',
  version: trackedRulesSpec as AppSpec,
} satisfies CompilerOutcome
