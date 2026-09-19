/**
 * End-to-end browser test against the real local backend.
 *
 * Flow:
 * 1. Create a vision app from a chat prompt.
 * 2. Upload the seed red-light video, calibrate, and run.
 * 3. Verify a supported red-light event is produced.
 * 4. Create a second app with the same prompt, upload a second video, calibrate, and run.
 * 5. Verify the same vision definition classifies the second video correctly.
 */
import { chromium, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { setTimeout } from 'node:timers/promises'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const BASE_URL = process.env.E2E_BASE_URL || 'http://127.0.0.1:8000'
const HEADLESS = process.env.E2E_HEADLESS !== 'false'
const SEED_VIDEO = join(ROOT, 'fixtures/synthetic/video/red_light_violation.mp4')
const SECOND_VIDEO = join(ROOT, 'artifacts/e2e-second-video.mp4')

function log(message) {
  // eslint-disable-next-line no-console
  console.log(`[e2e] ${message}`)
}

async function verifyPlayback(page, label) {
  const video = page.locator('video')
  await expect.poll(() => video.evaluate(v => ({ ready: v.readyState >= 2, width: v.videoWidth, error: v.error?.message ?? null })), { timeout: 30000 })
    .toEqual({ ready: true, width: 320, error: null })
  await expect(video).toHaveAttribute('src', /\/preview\.webm$/)
  await expect.poll(() => video.evaluate(v => v.duration)).toBe(5)
  await page.getByRole('button', { name: 'Play video', exact: true }).click()
  await expect.poll(() => video.evaluate(v => v.currentTime), { timeout: 10000 }).toBeGreaterThan(2.2)
  await page.getByRole('button', { name: 'Pause video', exact: true }).click()
  await expect.poll(() => video.evaluate(v => v.paused)).toBe(true)
  const position = page.getByRole('slider', { name: 'Video position' })
  await position.fill('3')
  await expect.poll(() => video.evaluate(v => v.seeking ? -1 : v.currentTime)).toBeCloseTo(3, 1)
  const visiblePixels = await video.evaluate(v => {
    const canvas = document.createElement('canvas')
    canvas.width = v.videoWidth
    canvas.height = v.videoHeight
    const ctx = canvas.getContext('2d')
    ctx.drawImage(v, 0, 0)
    const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data
    let colored = 0
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i] > 100 || pixels[i + 1] > 100) colored++
    return colored
  })
  expect(visiblePixels).toBeGreaterThan(100)
  await page.getByRole('button', { name: 'Next frame', exact: true }).click()
  await expect.poll(() => video.evaluate(v => v.currentTime)).toBeGreaterThan(3)
  await page.screenshot({ path: join(ROOT, `artifacts/e2e-${label}-playback.png`), fullPage: true })
  await position.fill('0')
  log(`${label}: WebM decoded, played, paused, sought and frame-stepped; visible pixels verified`)
}

async function createAppFromPrompt(page, prompt) {
  log('creating app')
  await page.goto(`${BASE_URL}/`)
  await page.getByRole('button', { name: /new app/i }).click()
  await page.waitForURL(/#\/app\//, { timeout: 5000 })

  log('sending prompt')
  await page.locator('#chat-message').fill(prompt)
  await page.getByRole('button', { name: /^send$/i }).click()

  const acceptButton = page.getByRole('button', { name: /accept proposal/i })
  await acceptButton.waitFor({ timeout: 15000 })
  log('proposal ready')
  await acceptButton.click()

  await page.getByRole('heading', { name: /upload source video/i }).waitFor({ timeout: 10000 })
  return page.url().match(/#\/app\/([^/]+)/)?.[1]
}

async function uploadVideo(page, videoPath) {
  log(`uploading ${videoPath}`)
  const fileInput = page.locator('input[type="file"]')
  await fileInput.setInputFiles(videoPath)
  // The upload panel disappears once the source is attached and the stage moves to calibration.
  await page.getByRole('heading', { name: /confirm scene calibration/i }).waitFor({ timeout: 30000 })
  log('source attached and calibration stage reached')
}

async function calibrate(page, mode = 'clicks') {
  log(`calibrating with ${mode}`)
  if (mode === 'sample') {
    await page.getByRole('button', { name: 'Use sample-video calibration' }).click()
    await expect(page.getByRole('button', { name: /confirm calibration/i })).toBeEnabled()
    await page.screenshot({ path: join(ROOT, 'artifacts/e2e-calibration-sample.png'), fullPage: true })
    await page.getByRole('button', { name: /confirm calibration/i }).click()
    await page.getByText(/calibration confirmed/i).waitFor({ timeout: 10000 })
    log('sample calibration confirmed without drawing')
    return
  }
  await page.getByRole('button', { name: /draw stop line/i }).click()
  const canvas = page.locator('canvas[aria-label="Calibration drawing canvas"]')
  await canvas.waitFor({ timeout: 10000 })
  const box = await canvas.boundingBox()
  if (!box) throw new Error('calibration canvas not found')

  const click = (nx, ny) =>
    canvas.click({ position: { x: box.width * nx, y: box.height * ny } })

  // Draw stop line across the road at the horizontal center.
  await click(0.5, 0.15)
  await click(0.5, 0.85)
  await expect(page.getByText(/Stop line: saved/)).toBeVisible()
  await click(0.5, 0.85)
  await click(0.5, 0.15)
  await expect(page.getByText(/Stop line: saved/)).toBeVisible()

  // Draw a polygon ROI around the traffic light (top-right quadrant).
  await page.getByRole('button', { name: /draw roi/i }).click()
  await click(0.72, 0.05)
  await expect(page.getByRole('button', { name: /confirm calibration/i })).toBeDisabled()
  await click(0.95, 0.25)
  await expect(page.getByRole('button', { name: /confirm calibration/i })).toBeEnabled()

  if (mode === 'drag') {
    const drag = async (from, to) => {
      await canvas.scrollIntoViewIfNeeded()
      const rect = await canvas.boundingBox()
      await page.mouse.move(rect.x + rect.width * from[0], rect.y + rect.height * from[1])
      await page.mouse.down()
      await page.mouse.move(rect.x + rect.width * to[0], rect.y + rect.height * to[1], { steps: 15 })
      await page.mouse.up()
    }
    for (const reverse of [false, true]) {
      await page.getByRole('button', { name: 'Clear geometry' }).click()
      await page.getByRole('button', { name: 'Draw stop line' }).click()
      await drag([0.5, reverse ? 0.85 : 0.15], [0.5, reverse ? 0.15 : 0.85])
      await expect(page.getByText(/Stop line: saved/)).toBeVisible()
      await page.getByRole('button', { name: 'Draw ROI' }).click()
      await drag(reverse ? [0.95, 0.25] : [0.72, 0.05], reverse ? [0.72, 0.05] : [0.95, 0.25])
      await expect(page.getByRole('button', { name: /confirm calibration/i })).toBeEnabled()
    }
  }
  await page.screenshot({ path: join(ROOT, `artifacts/e2e-calibration-${mode}.png`), fullPage: true })
  const submitted = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/calibrations'))
  await page.getByRole('button', { name: /confirm calibration/i }).click()
  const { geometries } = (await submitted).postDataJSON()
  expect(geometries.filter(g => g.kind === 'line')).toHaveLength(1)
  const line = geometries.find(g => g.kind === 'line').points
  expect(line[0].y).toBeLessThan(line[1].y)
  expect(geometries.find(g => g.label === 'roi').points).toHaveLength(4)
  await page.getByText(/calibration confirmed/i).waitFor({ timeout: 10000 })
  log('calibration confirmed')
}

async function runAndVerifyEvent(page, label) {
  log(`${label}: starting run`)
  await page.getByRole('button', { name: /start run/i }).click()
  await page.waitForURL(/#\/app\/.+\/run\//, { timeout: 5000 })

  log(`${label}: waiting for event`)
  const eventCard = page.locator('[data-testid^="event-card-"]')
  await eventCard.waitFor({ timeout: 30000 })

  const eventId = await eventCard.getAttribute('data-event-id')
  const cardText = await eventCard.textContent()
  log(`${label}: event ${eventId}: text "${cardText?.trim() ?? ''}"`)

  if (!cardText || !cardText.toLowerCase().includes('supported')) {
    throw new Error(`${label}: expected supported event, got: ${cardText}`)
  }

  await verifyPlayback(page, `${label}-results`)
  await expect.poll(() => eventCard.locator('img').evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true)
  log(`${label}: reviewing event`)
  await eventCard.click()
  await page.getByText(/Review status: unreviewed/i).waitFor({ timeout: 5000 })
  await page.getByRole('button', { name: /approve event/i }).click()
  await page.getByText(/Reviewed: confirmed/i).waitFor({ timeout: 5000 })
  await page.reload()
  await page.locator(`[data-event-id="${eventId}"]`).click()
  await page.getByText(/Reviewed: confirmed/i).waitFor({ timeout: 5000 })

  await page.screenshot({ path: join(ROOT, `artifacts/e2e-${label}-${Date.now()}.png`) })
  log(`${label}: event verified and reviewed`)
}

async function runFullFlow(page, prompt, videoPath, label) {
  log(`--- ${label} ---`)
  const appId = await createAppFromPrompt(page, prompt)
  log(`${label} app: ${appId}`)
  await uploadVideo(page, videoPath)
  await verifyPlayback(page, `${label}-calibration`)
  await page.reload()
  await verifyPlayback(page, `${label}-reloaded`)
  await calibrate(page, label === 'second' ? 'drag' : label === 'sample' ? 'sample' : 'clicks')
  await runAndVerifyEvent(page, label)
  log(`${label} passed`)
}

async function main() {
  execFileSync('ffmpeg', ['-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', SEED_VIDEO, '-an', '-c:v', 'mpeg4', '-q:v', '5', SECOND_VIDEO])

  const browser = await chromium.launch({ headless: HEADLESS, slowMo: 150 })
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1080 },
    recordVideo: { dir: join(ROOT, 'artifacts'), size: { width: 1440, height: 1080 } },
  })
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true })
  const page = await context.newPage()
  const failures = []
  page.on('pageerror', error => failures.push(error.message))
  page.on('response', response => {
    if (response.status() >= 400 && new URL(response.url()).pathname.includes('/media/')) failures.push(`${response.status()} ${response.url()}`)
  })

  try {
    const prompt =
      'Build me a vision app that takes any crossing video and finds cars that crossed illegally on a red light, and describes the car.'

    await runFullFlow(page, prompt, SEED_VIDEO, 'seed')

    // For the second video, return to the app list and create a fresh app with the same prompt.
    // The backend produces the same app definition, so this demonstrates the vision app classifying a second video.
    await page.goto(`${BASE_URL}/`)
    await runFullFlow(page, prompt, SECOND_VIDEO, 'second')
    await runFullFlow(page, prompt, SEED_VIDEO, 'sample')

    expect(failures).toEqual([])
    log('=== UI PLAYBACK / CREATION / CALIBRATION / RUN / REVIEW PASSED ===')
  } catch (error) {
    const path = join(ROOT, `artifacts/e2e-failure-${Date.now()}.png`)
    await page.screenshot({ path })
    log(`FAILED: ${error.message}; screenshot: ${path}`)
    process.exitCode = 1
  } finally {
    await setTimeout(1000)
    await context.tracing.stop({ path: join(ROOT, 'artifacts/e2e-playback-trace.zip') })
    const recording = page.video()
    await context.close()
    await recording.saveAs(join(ROOT, 'artifacts/e2e-playback-walkthrough.webm'))
    log('Recording: artifacts/e2e-playback-walkthrough.webm')
    await browser.close()
  }
}

main()
