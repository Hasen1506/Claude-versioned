import { defineConfig } from "@playwright/test";

// The engine serves the built client (run `npm run build` first). Locally a pre-installed Chromium
// can be used via PW_CHROMIUM=/path/to/chrome; CI installs Playwright's own browser.
const port = 8765;
// a second server that sends mail, to a mail server kept by the tests (e2e/smtp_sink.py), for e2e/mail.spec.ts
const mailPort = 8766;
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    launchOptions: process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {},
  },
  webServer: [
    {
      command: `python3 -m uvicorn scp.api.app:app --port ${port}`,
      cwd: "../engine",
      env: { SCP_DB: ":memory:" },   // a fresh version store per run
      url: `http://127.0.0.1:${port}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "python3 e2e/smtp_sink.py",
      url: "http://127.0.0.1:2526/messages",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `python3 -m uvicorn scp.api.app:app --port ${mailPort}`,
      cwd: "../engine",
      env: { SCP_DB: ":memory:", SCP_SMTP_HOST: "127.0.0.1", SCP_SMTP_PORT: "2525", SCP_SMTP_TLS: "none",
             SCP_SMTP_FROM: "plan@scp.example", SCP_PUBLIC_URL: `http://127.0.0.1:${mailPort}`, SCP_SCHEDULER: "0" },
      url: `http://127.0.0.1:${mailPort}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
