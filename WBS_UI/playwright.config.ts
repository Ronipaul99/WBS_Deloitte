import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testIgnore: '**/fullstack/**',
  outputDir: './test-results-phase-06',
  fullyParallel: true,
  workers: 2,
  reporter: 'line',
  webServer: {
    command: 'npm run dev -- --mode e2e --host 127.0.0.1 --port 5176',
    url: 'http://127.0.0.1:5176',
    reuseExistingServer: true,
  },
  use: {
    baseURL: 'http://127.0.0.1:5176',
    screenshot: 'only-on-failure',
  },
})
