import { expect, test } from "@playwright/test";
import { login, openFirstPendingFromInbox, seedPendingApproval } from "./helpers";

test("reject a proposal: a reason is required", async ({ page, request }) => {
  await seedPendingApproval(request);
  await login(page);
  await openFirstPendingFromInbox(page);

  await page.getByRole("button", { name: "Reject" }).click();
  const confirm = page.getByRole("button", { name: "Confirm rejection" });
  await expect(confirm).toBeDisabled();

  await page.getByTestId("reject-reason").fill("Budget is too low for this scope");
  await expect(confirm).toBeEnabled();
  await confirm.click();

  const result = page.getByTestId("decision-result");
  await expect(result).toBeVisible();
  await expect(result).toContainText("rejected");

  // The rejection reason feeds the analytics screen.
  await page.goto("/analytics");
  await expect(page.getByText("Budget is too low for this scope")).toBeVisible();
});
