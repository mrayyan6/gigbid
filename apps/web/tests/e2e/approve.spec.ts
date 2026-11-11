import { expect, test } from "@playwright/test";
import { login, openFirstPendingFromInbox, seedPendingApproval } from "./helpers";

test("approve a proposal: pending approval survives a refresh, then is submitted", async ({ page, request }) => {
  await seedPendingApproval(request);
  await login(page);
  await openFirstPendingFromInbox(page);

  // A page refresh never loses the pending approval.
  await page.reload();
  await expect(page.getByTestId("approval-panel")).toBeVisible();

  // Evidence is visible on hover or focus of a claim, and the dry run shows the cost.
  const claim = page.getByTestId("evidence-claim").first();
  await claim.focus();
  await expect(page.getByTestId("evidence-panel")).toBeVisible();
  await expect(page.getByTestId("dry-run")).toContainText("Connects cost");

  await page.getByRole("button", { name: "Approve and send" }).click();
  const result = page.getByTestId("decision-result");
  await expect(result).toBeVisible();
  await expect(result).toContainText("Decision recorded");
  await expect(result).toContainText("completed");
});
