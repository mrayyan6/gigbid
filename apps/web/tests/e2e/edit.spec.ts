import { expect, test } from "@playwright/test";
import { login, openFirstPendingFromInbox, seedPendingApproval } from "./helpers";

test("edit a draft: the diff is shown before the edit is submitted", async ({ page, request }) => {
  await seedPendingApproval(request);
  await login(page);
  await openFirstPendingFromInbox(page);

  await page.getByRole("button", { name: "Edit draft" }).click();
  const box = page.getByTestId("edit-textarea");
  await expect(box).toBeVisible();
  await expect(page.getByRole("button", { name: "Review changes" })).toBeDisabled();

  const added = " I can start this week.";
  const current = await box.inputValue();
  await box.fill(current + added);
  await page.getByRole("button", { name: "Review changes" }).click();

  const diff = page.getByTestId("diff-view");
  await expect(diff).toBeVisible();
  await expect(diff).toContainText("I can start this week.");

  await page.getByRole("button", { name: "Approve edited version" }).click();
  const result = page.getByTestId("decision-result");
  await expect(result).toBeVisible();
  await expect(result).toContainText("Decision recorded");
});
