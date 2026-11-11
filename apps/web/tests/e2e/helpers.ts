import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const REVIEWER = {
  email: "reviewer@gigbid.test",
  password: "e2e-reviewer-pass",
};

const API = "http://localhost:8000";

type JobRow = { job_id: string; thread_id?: string | null; title: string };

/** Sign in through the real login form. Leaves the page on onboarding or the inbox. */
export async function login(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(REVIEWER.email);
  await page.getByLabel("Password").fill(REVIEWER.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/(onboarding|inbox)/);
}

export async function apiToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/auth/login`, { data: REVIEWER });
  expect(res.ok()).toBeTruthy();
  const body = (await res.json()) as { access_token: string };
  return body.access_token;
}

/**
 * Start bid runs through the API until one is waiting for approval. Each call uses a job that
 * has no run yet, so every test gets its own pending approval. Returns the thread id.
 */
export async function seedPendingApproval(request: APIRequestContext): Promise<string> {
  const token = await apiToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  const jobsRes = await request.get(`${API}/api/jobs?limit=60`, { headers });
  expect(jobsRes.ok()).toBeTruthy();
  const jobs = (await jobsRes.json()) as JobRow[];
  for (const job of jobs.filter((j) => !j.thread_id).slice(0, 25)) {
    const start = await request.post(`${API}/api/runs`, { headers, data: { job_id: job.job_id } });
    if (!start.ok()) continue;
    const { thread_id } = (await start.json()) as { thread_id: string };
    for (let i = 0; i < 40; i++) {
      const run = await request.get(`${API}/api/runs/${encodeURIComponent(thread_id)}`, { headers });
      const status = ((await run.json()) as { status: string }).status;
      if (status === "awaiting_approval") return thread_id;
      if (status !== "queued" && status !== "running") break;
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  throw new Error("No job reached awaiting_approval. Is the API running with the graph enabled?");
}

export async function setMarketplaceDown(request: APIRequestContext, down: boolean): Promise<void> {
  const res = await request.post(`${API}/api/test/marketplace-down`, { data: { down } });
  expect(res.ok()).toBeTruthy();
}

/** Open the pending proposal from the inbox strip, as a user would. */
export async function openFirstPendingFromInbox(page: Page): Promise<void> {
  await page.goto("/inbox");
  const strip = page.getByTestId("pending-approvals");
  await expect(strip).toBeVisible();
  await strip.getByRole("link", { name: "Review proposal" }).first().click();
  await expect(page.getByTestId("approval-panel")).toBeVisible();
}
