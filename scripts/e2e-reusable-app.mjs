import { chromium, expect } from '@playwright/test'
import { mkdir, writeFile, access } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const terminalStates = ['succeeded', 'failed', 'cancelled', 'partial']
const pathname = response => new URL(response.url()).pathname
const postResponse = (page, path) => page.waitForResponse(response => response.request().method() === 'POST' && pathname(response) === path, { timeout: 180000 })

async function responseJSON(response) {
  const value = await response.json()
  expect(response.ok(), `${response.status()} ${pathname(response)}: ${JSON.stringify(value)}`).toBe(true)
  return value
}

export async function verifyAllMedia(page, report, label, required = false) {
  const videos = page.locator('video')
  if (required) await expect(videos.first()).toBeVisible()
  for (let i = 0; i < await videos.count(); i++) {
    const video = videos.nth(i)
    await expect.poll(() => video.evaluate(v => v.readyState >= 2 && v.videoWidth > 0 && Number.isFinite(v.duration) && v.duration > 0 && v.error === null), { timeout: 30000 }).toBe(true)
    const metadata = await video.evaluate(v => ({ src: v.currentSrc, duration: v.duration, width: v.videoWidth, height: v.videoHeight }))
    const controls = video.locator('../..')
    const position = controls.getByRole('slider', { name: 'Video position', exact: true })
    await video.evaluate(v => { v.muted = true })
    if (await position.count()) {
      await position.fill('0')
      await controls.getByRole('button', { name: 'Play video', exact: true }).click()
    } else await video.evaluate(async v => { v.currentTime = 0; await v.play() })
    await expect.poll(() => video.evaluate(v => v.currentTime), { timeout: 10000 }).toBeGreaterThan(0.1)
    const target = Math.min(metadata.duration * 0.6, metadata.duration - 0.1)
    if (await position.count()) {
      await controls.getByRole('button', { name: 'Pause video', exact: true }).click()
      await position.fill(String(target))
    } else await video.evaluate((v, time) => { v.pause(); v.currentTime = time }, target)
    await expect.poll(() => video.evaluate(v => v.seeking ? -1 : v.currentTime)).toBeCloseTo(target, 1)
    const pixels = await video.evaluate(v => {
      const canvas = document.createElement('canvas')
      canvas.width = v.videoWidth
      canvas.height = v.videoHeight
      const ctx = canvas.getContext('2d')
      ctx.drawImage(v, 0, 0)
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      return data.some((value, index) => index % 4 !== 3 && value > 30)
    })
    expect(pixels, `${label}: decoded video has visible image pixels`).toBe(true)
    report.media.push({ label, ...metadata, loaded: true, played: true, sought: true })
  }
  const thumbnails = page.locator('img[alt="evidence thumbnail"], img[alt="evidence"]')
  for (let i = 0; i < await thumbnails.count(); i++) {
    await expect.poll(() => thumbnails.nth(i).evaluate(img => img.complete && img.naturalWidth > 0), { timeout: 30000 }).toBe(true)
  }
}

export async function runReusableAcceptance(page, options = {}) {
  const report = options.report ?? {}
  Object.assign(report, { status: 'running', provenance: options.mock ? 'mocked UI contract; not live accuracy' : 'real backend; runtime mode pending', responses: [], media: [], runs: [], uncertainties: [] })
  const pending = new Set()
  const errors = []
  let runtime
  const observe = response => {
    const path = pathname(response)
    if (!path.startsWith('/v1/')) return
    const task = response.json().then(value => {
      const method = response.request().method()
      report.responses.push({ path, method, status: response.status(), body: value })
      if (path === '/v1/runtime') runtime = value
    }).catch(() => {}).finally(() => pending.delete(task))
    pending.add(task)
  }
  page.on('response', observe)
  page.on('dialog', dialog => { errors.push(`Unexpected dialog: ${dialog.message()}`); void dialog.dismiss() })
  page.on('pageerror', error => errors.push(error.message))
  const guard = async route => {
    const request = route.request()
    if (request.method() === 'POST' && /\/(turns|clarifications|runs)$/.test(new URL(request.url()).pathname)) {
      if (!runtime || ((runtime.analysis_mode === 'gemini' || runtime.external_processing) && !options.liveApproved && !options.mock)) {
        errors.push('External-processing request blocked: E2E_LIVE_APPROVED=1 is required')
        return route.abort('blockedbyclient')
      }
    }
    await route.continue()
  }
  await page.route('**/v1/**', guard)
  const screenshot = async label => {
    if (options.artifactDir) await page.screenshot({ path: join(options.artifactDir, `${label}.png`), fullPage: true })
  }
  const authorize = async () => {
    if (runtime.analysis_mode === 'gemini' || runtime.external_processing) {
      expect(options.liveApproved || options.mock, 'Live processing requires explicit E2E_LIVE_APPROVED=1 approval').toBe(true)
    }
  }
  const upload = async (path, label, appId) => {
    const attached = postResponse(page, `/v1/apps/${appId}/source`)
    await page.locator('input[type="file"]').setInputFiles(path)
    const app = await responseJSON(await attached)
    expect(app.source?.asset_id).toBeTruthy()
    await expect(page.getByText(`Current source: ${app.source.asset_id}`, { exact: false })).toBeVisible()
    await verifyAllMedia(page, report, `${label}-workspace`)
    await screenshot(`${label}-uploaded`)
    return app
  }
  const calibrateIfNeeded = async (app, label, appId) => {
    if (app.requires_calibration ?? app.spec?.kind !== 'semantic_windows') {
      await verifyAllMedia(page, report, `${label}-calibration`, true)
      await screenshot(`${label}-calibration`)
      const saved = postResponse(page, `/v1/apps/${appId}/calibrations`)
      await page.getByRole('button', { name: 'Confirm calibration', exact: true }).click()
      await responseJSON(await saved)
      await expect(page.getByText('Source ready and calibration confirmed.', { exact: true })).toBeVisible()
    }
  }
  const inspectResults = async (runId, label) => {
    await expect(page.getByLabel('Run result')).toHaveAttribute('data-status', /^(succeeded|failed|cancelled)$/, { timeout: 180000 })
    await expect(page.getByLabel('Run result')).toHaveAttribute('data-status', 'succeeded')
    await verifyAllMedia(page, report, `${label}-results`, true)
    await expect(page.locator('[data-testid^="event-card-"]')).toHaveCount(0)
    await screenshot(`${label}-results`)
    await Promise.all([...pending])
    const result = report.responses.filter(item => item.path === `/v1/runs/${runId}` && terminalStates.includes(item.body.run?.status)).at(-1)?.body
    expect(result, 'Run response must originate from UI polling').toBeTruthy()
    expect(result.run.status, JSON.stringify(result)).toBe('succeeded')
    for (const event of result.events) {
      expect(event.run_id).toBe(result.run.id)
      expect(event.spec_version_id).toBe(result.run.version_id)
    }
    return result
  }
  const start = async (appId, label) => {
    await authorize()
    const started = postResponse(page, `/v1/apps/${appId}/runs`)
    await page.getByRole('button', { name: 'Run app', exact: true }).click()
    const { run_id: runId } = await responseJSON(await started)
    await expect(page).toHaveURL(new RegExp(`/run/${runId}$`))
    const result = await inspectResults(runId, label)
    report.runs.push(result)
    return result
  }
  const runNewVideo = async (path, label, appId, needsCalibration) => {
    await authorize()
    const attached = postResponse(page, `/v1/apps/${appId}/source`)
    const calibrated = needsCalibration ? postResponse(page, `/v1/apps/${appId}/calibrations`) : null
    const started = postResponse(page, `/v1/apps/${appId}/runs`)
    await page.locator('input[type="file"]').setInputFiles(path)
    const app = await responseJSON(await attached)
    if (calibrated) await responseJSON(await calibrated)
    const { run_id: runId } = await responseJSON(await started)
    await expect(page).toHaveURL(new RegExp(`/run/${runId}$`))
    await verifyAllMedia(page, report, `${label}-workspace`)
    await screenshot(`${label}-uploaded`)
    const result = await inspectResults(runId, label)
    report.runs.push(result)
    return { app, result }
  }
  try {
    await page.goto(options.baseURL ?? 'http://127.0.0.1:8000')
    const created = postResponse(page, '/v1/apps')
    await page.getByRole('button', { name: 'New app', exact: true }).click()
    const appId = (await responseJSON(await created)).id
    await expect(page).toHaveURL(new RegExp(`#\/app\/${appId}$`))
    await expect.poll(() => runtime, { timeout: 15000 }).toBeTruthy()
    report.runtime = runtime
    report.provenance = options.mock ? report.provenance : `${runtime.analysis_mode} real backend`
    if (options.mode) expect(runtime.analysis_mode, 'E2E_MODE must match server runtime').toBe(options.mode)
    await expect(page.getByLabel('Analysis mode')).toContainText(runtime.analysis_mode === 'gemini' ? 'Model-assisted review' : 'NOT actual detection')
    if (runtime.analysis_mode === 'gemini' || runtime.external_processing) {
      expect(options.liveApproved || options.mock, 'Refusing external calls without E2E_LIVE_APPROVED=1').toBe(true)
      expect(runtime.configured, 'Server requires configured provider credentials').toBe(true)
      report.uncertainties.push('Model observations can be incomplete or wrong; positive/negative fixture assertions do not establish general accuracy or legal violations.')
    } else report.uncertainties.push('Scripted output is synthetic and does not demonstrate detection accuracy.')
    const seedPath = options.seedVideo ?? process.env.E2E_SEED_VIDEO ?? join(ROOT, 'fixtures/synthetic/video/red_light_violation.mp4')
    const secondPath = options.secondVideo ?? process.env.E2E_SECOND_VIDEO ?? join(ROOT, 'fixtures/synthetic/video/green_light_crossing.mp4')
    expect(resolve(seedPath)).not.toBe(resolve(secondPath))
    await access(seedPath)
    await access(secondPath)
    const seedApp = await upload(seedPath, 'seed', appId)
    report.appId = appId
    report.seedAssetId = seedApp.source.asset_id
    await authorize()
    await page.getByRole('textbox', { name: 'Message', exact: true }).fill(options.prompt ?? 'Find cars crossing the stop line while the traffic light governing their movement is red. Describe each observed car and the visible signal. Do not flag cars crossing on green. Treat uncertain observations as uncertain, not established legal violations.')
    const proposed = postResponse(page, `/v1/apps/${appId}/turns`)
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    const proposal = await responseJSON(await proposed)
    expect(proposal.outcome?.kind, JSON.stringify(proposal)).toBe('proposed_version')
    await expect(page.getByRole('button', { name: 'Accept proposal', exact: true })).toBeVisible({ timeout: 180000 })
    await screenshot('proposal')
    const accepted = postResponse(page, `/v1/apps/${appId}/versions`)
    await page.getByRole('button', { name: 'Accept proposal', exact: true }).click()
    const definition = await responseJSON(await accepted)
    report.definition = definition.spec
    await expect(page.getByRole('region', { name: 'Reusable app definition' })).toBeVisible()
    await calibrateIfNeeded(definition, 'seed', appId)
    await page.getByRole('button', { name: 'Run app', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`#/app/${appId}/use$`))
    const first = await start(appId, 'seed')
    expect(first.run.asset_id).toBe(seedApp.source.asset_id)
    expect(first.run.is_seed_run).toBe(true)
    expect(first.run.version_id).toBeTruthy()
    await page.getByRole('link', { name: '← App' }).click()
    await expect(page).toHaveURL(new RegExp(`#/app/${appId}/use$`))
    const needsCalibration = definition.requires_calibration ?? definition.spec?.kind !== 'semantic_windows'
    const { app: secondApp, result: second } = await runNewVideo(secondPath, 'second', appId, needsCalibration)
    expect(secondApp.id).toBe(appId)
    expect(secondApp.seed_asset_id).toBe(seedApp.source.asset_id)
    expect(secondApp.published_version_id).toBe(first.run.version_id)
    expect(secondApp.spec).toEqual(definition.spec)
    expect(secondApp.source.asset_id).not.toBe(seedApp.source.asset_id)
    await expect(page.getByRole('button', { name: 'Accept proposal', exact: true })).toHaveCount(0)
    expect(second.run.app_id).toBe(first.run.app_id)
    expect(second.run.app_id).toBe(appId)
    expect(second.run.version_id).toBe(first.run.version_id)
    expect(second.run.asset_id).toBe(secondApp.source.asset_id)
    expect(second.run.asset_id).not.toBe(first.run.asset_id)
    expect(second.run.is_seed_run).toBe(false)
    await page.getByRole('link', { name: '← App' }).click()
    await expect(page.getByRole('heading', { name: 'Run history', exact: true })).toBeVisible()
    await page.reload()
    for (const result of [first, second]) {
      const link = page.getByRole('link', { name: `Run ${result.run.id}`, exact: true })
      await expect(link.locator('..')).toContainText(result.run.asset_id)
      await expect(link.locator('..')).toContainText(result.run.version_id)
    }
    await screenshot('retained-run-history')
    for (const [index, previous] of [first, second].entries()) {
      await page.getByRole('link', { name: `Run ${previous.run.id}`, exact: true }).click()
      const retained = await inspectResults(previous.run.id, `history-${index}`)
      expect(retained.run.asset_id).toBe(previous.run.asset_id)
      expect(retained.run.version_id).toBe(previous.run.version_id)
      expect(retained.run.source).toEqual(previous.run.source)
      expect(retained.events).toEqual(previous.events)
      await page.getByRole('link', { name: '← App' }).click()
    }
    await Promise.all([...pending])
    const history = report.responses.filter(item => item.path === `/v1/apps/${appId}/runs` && item.method === 'GET').at(-1)?.body.runs
    expect(history?.map(run => run.id)).toEqual(expect.arrayContaining([first.run.id, second.run.id]))
    expect(report.responses.filter(item => item.path === '/v1/apps' && item.method === 'POST')).toHaveLength(1)
    expect(report.responses.filter(item => item.path.endsWith('/versions') && item.method === 'POST')).toHaveLength(1)
    expect(report.responses.filter(item => item.path.endsWith('/turns') && item.method === 'POST')).toHaveLength(1)
    expect(errors).toEqual([])
    if (options.mock) {
      for (const result of [first, second]) {
        const states = report.responses.filter(item => item.path === `/v1/runs/${result.run.id}`).map(item => item.body.run.status)
        expect(states).toEqual(expect.arrayContaining(['queued', 'running', 'succeeded']))
      }
    }
    report.accuracy = { seedSupported: first.events.filter(event => event.machine_decision === 'supported').length, secondSupported: second.events.filter(event => event.machine_decision === 'supported').length, provenance: report.provenance }
    report.uncertainObservations = [first, second].flatMap(result => result.events.filter(event => ['candidate', 'inconclusive'].includes(event.machine_decision)).map(event => ({ run_id: result.run.id, event })))
    if (runtime.analysis_mode === 'gemini') {
      const present = first.events.filter(event => event.facts?.decision === 'present' && event.facts?.provider === 'gemini')
      expect(present.length, `Red fixture expected a model-reported crossing; actual output: ${JSON.stringify(first.events)}`).toBeGreaterThan(0)
      expect(second.events, 'Green fixture must report absence, not a crossing or uncertain result').toHaveLength(0)
      report.accuracy.seedPresent = present.length
      report.accuracy.secondAbsent = true
    } else if (options.mock) {
      expect(report.accuracy.seedSupported).toBeGreaterThan(0)
      expect(report.accuracy.secondSupported).toBe(0)
    }
    report.status = 'passed'
    return report
  } catch (error) {
    report.status = 'failed'
    report.failure = error.message
    await screenshot('failure')
    throw error
  } finally {
    await Promise.all([...pending])
    page.off('response', observe)
    await page.unroute('**/v1/**', guard)
  }
}

async function main() {
  const artifactDir = resolve(process.env.E2E_ARTIFACT_DIR ?? join(ROOT, 'artifacts/reusable-app', new Date().toISOString().replaceAll(':', '-')))
  await mkdir(artifactDir, { recursive: true })
  const browser = await chromium.launch({ headless: process.env.E2E_HEADLESS !== 'false', slowMo: 100 })
  const context = await browser.newContext({ viewport: { width: 1440, height: 1080 }, recordVideo: { dir: artifactDir, size: { width: 1440, height: 1080 } } })
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  const page = await context.newPage()
  const recording = page.video()
  const report = {}
  try {
    await runReusableAcceptance(page, { baseURL: process.env.E2E_BASE_URL, mode: process.env.E2E_MODE, liveApproved: process.env.E2E_LIVE_APPROVED === '1', artifactDir, report })
    console.log(`Reusable-app UI acceptance passed (${report.provenance}); ${artifactDir}`)
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  } finally {
    await writeFile(join(artifactDir, 'report.json'), JSON.stringify(report, null, 2))
    await context.tracing.stop({ path: join(artifactDir, 'trace.zip') })
    await context.close()
    await recording.saveAs(join(artifactDir, 'walkthrough.webm'))
    await browser.close()
    console.log(`Recording, trace, screenshots and observed UI responses: ${artifactDir}`)
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
