import os from 'node:os'
import path from 'node:path'
import { defineConfig, devices } from '@playwright/test'

// The smoke test runs the real stack: the backend on a fresh demo database (seeded on start,
// compute in threads) and Vite proxying /api to it. `make e2e` / `npm run e2e`.
const API_PORT = 8011
const WEB_PORT = 5179
const db = path.join(os.tmpdir(), `paintmixer-e2e-${process.pid}.db`)

export default defineConfig({
  testDir: 'e2e',
  timeout: 60_000,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    ...devices['Desktop Chrome'],
    viewport: { width: 1194, height: 834 }, // the design's tablet
    trace: 'off',
  },
  webServer: [
    {
      command: `uv run uvicorn paintmixer.api.app:app --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/api/v1/health`,
      env: {
        PAINTMIXER_DATABASE_URL: `sqlite:///${db}`,
        PAINTMIXER_SEED_DEMO: '1',
        PAINTMIXER_COMPUTE_WORKERS: '0',
      },
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { PAINTMIXER_API: `http://127.0.0.1:${API_PORT}` },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
})
