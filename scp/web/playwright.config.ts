import { defineConfig } from "@playwright/test";

// The engine serves the built client (run `npm run build` first). Locally a pre-installed Chromium
// can be used via PW_CHROMIUM=/path/to/chrome; CI installs Playwright's own browser.
const port = 8765;
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: {
    command: `python3 -m uvicorn scp.api.app:app --port ${port}`,
    cwd: "../engine",
    env: { SCP_DB: ":memory:" },   // a fresh version store per run

    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
