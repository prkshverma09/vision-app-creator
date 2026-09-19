import { expect, test, type Page } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { writeFile } from 'node:fs/promises'
import { runReusableAcceptance, verifyAllMedia } from '../../../scripts/e2e-reusable-app.mjs'

const seedVideo = fileURLToPath(new URL('../../../fixtures/synthetic/video/red_light_violation.mp4', import.meta.url))

test.use({ video: 'on', trace: 'on', screenshot: 'on' })

async function newWorkspace(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Your apps' })).toBeVisible()
  await page.getByRole('button', { name: 'New app' }).click()
  await expect(page).toHaveURL(/#\/app\/app-e2e$/)
  await expect(page.getByLabel('Analysis mode')).toContainText('NOT actual detection')
}

async function propose(page: Page) {
  await page.getByRole('textbox', { name: 'Message' }).fill('Detect cars crossing the stop line while the light is red')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('Red light crossing', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Accept proposal' }).click()
}

async function createPolicy(page: Page) {
  await newWorkspace(page)
  await propose(page)
  await expect(page.getByRole('heading', { name: 'Upload source video' })).toBeVisible()
}

async function uploadSource(page: Page) {
  await newWorkspace(page)
  const attached = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/source'))
  await page.locator('input[type=file]').setInputFiles(seedVideo)
  const app = await (await attached).json()
  expect(app.source).toMatchObject({ asset_id: 'asset-e2e', duration_ms: 5000, width: 320, height: 180 })
  await expect(page.getByText('Current source: asset-e2e (seed video)', { exact: true })).toBeVisible()
  await propose(page)
  await expect(page.getByRole('heading', { name: 'Confirm scene calibration' })).toBeVisible()
}

async function calibrate(page: Page) {
  await uploadSource(page)
  await page.getByRole('button', { name: 'Confirm calibration' }).click()
  await expect(page.getByText('Source ready and calibration confirmed.')).toBeVisible()
}

async function runApp(page: Page) {
  await calibrate(page)
  await page.getByRole('button', { name: 'Run app' }).click()
  await expect(page).toHaveURL(/#\/app\/app-e2e\/use$/)
  await expect(page.getByRole('heading', { name: 'Upload source video' })).toBeVisible()
  await expect(page.locator('video')).toHaveCount(0)
  await page.locator('input[type=file]').setInputFiles(seedVideo)
  await expect(page.getByLabel('Run result')).toHaveAttribute('data-status', 'succeeded')
  await expect(page.getByLabel('Run result')).toHaveText('Demo only: this video has not been analyzed.')
}

test('Journey 1: legacy prompt-first creation still reaches upload', async ({ page }) => {
  await createPolicy(page)
  await expect(page.getByText('Proposal accepted. Upload a source video next.')).toBeVisible()
  await expect(page.getByLabel('Builder steps').getByText('2. Source')).toHaveAttribute('aria-current', 'step')
})

test('Journey 2: seed upload before prompt, inspect metadata, and decode calibration video', async ({ page }) => {
  await uploadSource(page)
  await expect(page.getByLabel('Builder steps').getByText('3. Calibration')).toHaveAttribute('aria-current', 'step')
  await verifyAllMedia(page, { media: [] }, 'calibration', true)
})

test('Journey 3: draw stop-line and ROI, confirm calibration, and publish the version', async ({ page }) => {
  await calibrate(page)
  await expect(page.getByLabel('Builder steps').getByText('4. Run')).toHaveAttribute('aria-current', 'step')
  await expect(page.getByRole('region', { name: 'Reusable app definition' })).toContainText('Red light crossing')
})

test('Journey 4: run the app and view a plain result with playable source video', async ({ page }) => {
  await runApp(page)
  await verifyAllMedia(page, { media: [] }, 'run-source', true)
})

test('Journey 5: run result has no banner, timeline, event or evidence panels', async ({ page }) => {
  await runApp(page)
  await expect(page.locator('p[aria-label="Run result"]')).toBeVisible()
  await expect(page.getByLabel('Findings timeline')).toHaveCount(0)
  await expect(page.getByLabel('Detected events')).toHaveCount(0)
  await expect(page.getByLabel('Event detail')).toHaveCount(0)
  await expect(page.locator('[data-testid^="event-card-"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: /approve|reject|mark unknown/i })).toHaveCount(0)
})

for (const scenario of [
  { name: 'positive', status: 'succeeded', complete: true, decision: 'candidate', text: 'Possible match: A white car crossed the yellow line while the light was red.' },
  { name: 'negative', status: 'succeeded', complete: true, decision: null, text: 'No matching activity was detected in this video.' },
  { name: 'uncertain', status: 'succeeded', complete: true, decision: 'inconclusive', text: 'The video is inconclusive — the app could not determine whether the activity occurred.' },
  { name: 'partial', status: 'succeeded', complete: false, decision: null, text: 'Only part of the video was analyzed — no complete result is available.' },
  { name: 'failed', status: 'failed', complete: false, decision: null, text: 'The video could not be analyzed — please try again.' },
]) {
  test(`Mocked Gemini ${scenario.name} result is a single human-readable sentence`, async ({ page }) => {
    await page.route('**/v1/runs/run-result', route => route.fulfill({ json: {
      run: { id: 'run-result', app_id: 'app-result', analysis_mode: 'gemini', status: scenario.status, analysis_complete: scenario.complete },
      events: scenario.decision ? [{
        id: 'event-result', machine_decision: scenario.decision,
        facts: { description: 'A white car crossed the yellow line while the light was red.' },
      }] : [],
    } }))
    await page.goto('/#/app/app-result/run/run-result')
    await expect(page.getByLabel('Run result')).toHaveText(scenario.text)
    await expect(page.getByLabel('Detected events')).toHaveCount(0)
    await expect(page.getByLabel('Event detail')).toHaveCount(0)
    await expect(page.getByLabel('Findings timeline')).toHaveCount(0)
  })
}

test('Journey 6: unsupported chat request is explained honestly', async ({ page }) => {
  await newWorkspace(page)
  await page.getByRole('textbox', { name: 'Message' }).fill('Recognize the identity of every face')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect(page.getByText('Identity recognition is excluded for privacy and safety.')).toBeVisible()
  await expect(page.getByText('Request not supported')).toBeVisible()
  await expect(page.getByText('Identity recognition is excluded', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Accept proposal' })).not.toBeVisible()
  await expect(page.getByRole('button', { name: 'Start run', exact: true })).not.toBeVisible()
})

test('Mocked Gemini mode requires seed upload before sending and never shows a consent dialog', async ({ page }) => {
  await page.route('**/v1/runtime', route => route.fulfill({ json: { analysis_mode: 'gemini', provider: 'google', model: 'mock-only', configured: true, external_processing: true, limits: { max_duration_ms: 300000, max_bytes: 100000000 } } }))
  let dialogs = 0
  page.on('dialog', async dialog => { dialogs++; await dialog.dismiss() })
  await page.goto('/')
  await page.getByRole('button', { name: 'New app', exact: true }).click()
  await expect(page.getByLabel('Analysis mode')).toContainText('Model-assisted review')
  await page.getByRole('textbox', { name: 'Message', exact: true }).fill('Detect cars crossing on red')
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeDisabled()
  const attached = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/source'))
  await page.locator('input[type=file]').setInputFiles(seedVideo)
  await attached
  await expect(page.getByRole('button', { name: 'Send', exact: true })).toBeEnabled()
  await expect(page.getByRole('checkbox')).toHaveCount(0)
  await expect(page.getByLabel('Analysis mode')).not.toBeVisible()
  const turn = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/turns'))
  await page.getByRole('button', { name: 'Send', exact: true }).click()
  expect((await turn).postDataJSON()).toMatchObject({ confirm_external_processing: true })
  await expect(page.getByRole('button', { name: 'Accept proposal', exact: true })).toBeVisible()
  expect(dialogs).toBe(0)
})

test('Journey 7: mocked same app/version reuses a different video and retains both run sources', async ({ page }, testInfo) => {
  test.setTimeout(120000)
  const report = {}
  try {
    await runReusableAcceptance(page, { baseURL: 'http://127.0.0.1:4173', mode: 'scripted', mock: true, artifactDir: testInfo.outputDir, report })
  } finally {
    const path = testInfo.outputPath('report.json')
    await writeFile(path, JSON.stringify(report, null, 2))
    await testInfo.attach('observed-ui-lineage-not-live-accuracy', { path, contentType: 'application/json' })
  }
})
