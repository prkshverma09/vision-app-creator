import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: '../apps/web/e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [['list'], ['json', { outputFile: '../artifacts/playwright/functional-results.json' }]],
  outputDir: '../artifacts/playwright/functional',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'functional-chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'pnpm --filter @vision-app/web build && node apps/web/e2e/mock-backend.mjs',
    cwd: '..',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
    timeout: 120_000,
    env: { VISION_APP_TEST_PROFILE: 'e2e-local-contract', VISION_APP_ADAPTER_PROVENANCE: 'scripted-compiler,recorded-detector' },
  },
})
