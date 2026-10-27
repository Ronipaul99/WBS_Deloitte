import { defineConfig } from '@playwright/test';

const baseURL = process.env.FULLSTACK_UI_URL ?? 'http://127.0.0.1:5187';

export default defineConfig({
  testDir: './tests/fullstack',
  outputDir: process.env.FULLSTACK_ARTIFACT_DIR ?? './test-results-fullstack',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 45_000,
  reporter: [['line']],
  use: {
    baseURL,
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
});
