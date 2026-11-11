import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// Starts the whole stack for the end to end tests: GigSim (9000), the API (8000, test mode, no
// DATABASE_URL, fresh temp SQLite per run) and the production Next server (3000).
const repoRoot = path.resolve(__dirname, "../..");
const python = path.join(repoRoot, ".venv", "Scripts", process.platform === "win32" ? "python.exe" : "python");
const tmp = path.join(os.tmpdir(), `gigbid-e2e-${process.pid}`);
const WEB_PORT = 3000;

export const REVIEWER = {
  email: "reviewer@gigbid.test",
  password: "e2e-reviewer-pass",
  persona: "ai_ml",
};

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `"${python}" -m uvicorn gigsim.app:app --port 9000`,
      cwd: repoRoot,
      url: "http://localhost:9000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: `"${python}" -m uvicorn apps.api.main:app --port 8000`,
      cwd: repoRoot,
      url: "http://localhost:8000/api/health",
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        REVIEWER_EMAIL: REVIEWER.email,
        REVIEWER_PASSWORD: REVIEWER.password,
        REVIEWER_PERSONA: REVIEWER.persona,
        GIGBID_TEST_MODE: "1",
        CHECKPOINT_DB: path.join(tmp, "checkpoints.sqlite"),
        DATABASE_URL: "",
        REDIS_URL: "",
      },
    },
    {
      command: `npx next start -p ${WEB_PORT}`,
      cwd: __dirname,
      url: `http://localhost:${WEB_PORT}/login`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { API_URL: "http://localhost:8000" },
    },
  ],
});
