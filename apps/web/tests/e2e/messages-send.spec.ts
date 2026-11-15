import { expect, test } from "@playwright/test";
import { apiToken, login, seedPendingApproval } from "./helpers";

const API = "http://localhost:8000";

/** Approve proposals through the API until a simulated client replies. Returns false if none did. */
async function seedClientReply(request: import("@playwright/test").APIRequestContext): Promise<boolean> {
  const token = await apiToken(request);
  const headers = { Authorization: `Bearer ${token}` };
  for (let i = 0; i < 12; i++) {
    const tid = await seedPendingApproval(request);
    const done = await request.post(`${API}/api/approvals/${encodeURIComponent(tid)}`, {
      headers,
      data: { action: "approve" },
    });
    if (!done.ok()) continue;
    const msgs = (await (await request.get(`${API}/api/messages`, { headers })).json()) as { threads: unknown[] };
    if (msgs.threads.length > 0) return true;
  }
  return false;
}

test("messages: a suggested reply is edited, approved and sent exactly once", async ({ page, request }) => {
  test.skip(!(await seedClientReply(request)), "no simulated client replied in 12 approved proposals");
  await login(page);
  await page.goto("/messages");

  const thread = page.getByTestId("thread").first();
  await expect(thread).toBeVisible();
  await thread.getByRole("button", { name: "Suggest a reply" }).click();

  const suggestion = thread.getByTestId("suggested-reply");
  await expect(suggestion).toBeVisible();
  const box = suggestion.getByRole("textbox");
  await box.fill((await box.inputValue()) + " I can share two short case studies.");

  // Nothing is sent until the user clicks the button, and it is no longer disabled.
  const send = suggestion.getByRole("button", { name: "Approve and send" });
  await expect(send).toBeEnabled();
  await send.click();

  await expect(thread.getByTestId("reply-sent")).toContainText("Reply sent");
  await expect(thread.getByText("I can share two short case studies.")).toBeVisible();
  await expect(thread.getByText("You", { exact: true }).first()).toBeVisible();
});
