import type { AppDetail } from './types'

/**
 * Builder workflow stages: chat → source upload → calibration → run.
 * Results live on the dedicated run route, not in this state machine.
 */
export type BuilderStage = 'chat' | 'source' | 'calibration' | 'run'

export const stageOrder: readonly BuilderStage[] = ['chat', 'source', 'calibration', 'run']

export const stageLabels: Record<BuilderStage, string> = {
  chat: 'Describe',
  source: 'Source video',
  calibration: 'Calibration',
  run: 'Run',
}

/**
 * Derive the current stage purely from server-side app state so a reload
 * reconstructs the workflow without any in-memory transcript.
 */
export function stageForApp(app: AppDetail): BuilderStage {
  if (!app.spec) return 'chat'
  if (!app.source) return 'source'
  if ((app.requires_calibration ?? app.spec.kind === 'tracked_rules') && !app.calibration_id) return 'calibration'
  return 'run'
}

export function stageIndex(stage: BuilderStage): number {
  return stageOrder.indexOf(stage)
}
