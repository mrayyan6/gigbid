import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("new user completes onboarding and the choices are saved", async ({ page }) => {
  await login(page);
  await expect(page).toHaveURL(/\/onboarding/);
  await expect(page.getByRole("heading", { name: "Set up your workspace" })).toBeVisible();

  // Upwork is shown but disabled, GigSim is the selected marketplace.
  await expect(page.getByRole("radio", { name: /Upwork/ })).toBeDisabled();
  await expect(page.getByRole("radio", { name: /GigSim/ })).toBeChecked();

  await page.getByLabel("Minimum hourly rate (USD)").fill("55");
  await page.getByLabel("Weekly Connects budget").fill("80");
  await page.getByLabel(/Keyword filters/).fill("rag, fastapi");
  await page.getByRole("button", { name: "Save and continue" }).click();

  await expect(page).toHaveURL(/\/inbox/);
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();

  await page.goto("/settings");
  await expect(page.getByLabel("Minimum hourly rate (USD)")).toHaveValue("55");
  await expect(page.getByLabel("Weekly Connects budget")).toHaveValue("80");
  await expect(page.getByLabel(/Keyword filters/)).toHaveValue("rag, fastapi");
});
