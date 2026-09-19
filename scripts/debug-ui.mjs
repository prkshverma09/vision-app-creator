import { chromium } from '@playwright/test'
import { writeFile } from 'node:fs/promises'

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:8000'
const ROOT = new URL('..', import.meta.url).pathname

const browser = await chromium.launch({ headless: false })
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })

await page.goto(BASE + '/')
await page.waitForTimeout(1500)
await page.screenshot({ path: `${ROOT}/artifacts/debug-home.png` })
await page.getByRole('button', { name: /new app/i }).click()
await page.waitForTimeout(1500)
await page.screenshot({ path: `${ROOT}/artifacts/debug-workspace.png` })

const prompt = 'Build me a vision app that takes any crossing video and finds cars that crossed illegally on a red light, and describes the car.'
await page.locator('#chat-message').fill(prompt)
await page.getByRole('button', { name: /^send$/i }).click()
await page.waitForTimeout(1500)
await page.screenshot({ path: `${ROOT}/artifacts/debug-after-send.png` })
const html = await page.content()
await writeFile(`${ROOT}/artifacts/debug-after-send.html`, html, 'utf8')
console.log('debug done')
await browser.close()
