import { defineConfig, devices } from "@playwright/test"

// The built UI (web/dist) served by the real Python server over a generated
// library: one server without authentication, one with an API key.
export const API_KEY = "e2e-key-0123456789abcdef0123456789" // gitleaks:allow

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: { ...devices["Desktop Chrome"], viewport: { width: 1600, height: 920 }, trace: "retain-on-failure" },
  projects: [
    { name: "app", testMatch: "app.spec.ts", use: { baseURL: "http://127.0.0.1:4791" } },
    { name: "auth", testMatch: "auth.spec.ts", use: { baseURL: "http://127.0.0.1:4792" } },
  ],
  webServer: [
    { command: "sh e2e/serve.sh 4791", url: "http://127.0.0.1:4791/api/health", timeout: 120_000 },
    { command: `sh e2e/serve.sh 4792 ${API_KEY}`, url: "http://127.0.0.1:4792/api/health", timeout: 120_000 },
  ],
})
