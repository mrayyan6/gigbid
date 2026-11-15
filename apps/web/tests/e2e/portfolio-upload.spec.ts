import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test("portfolio upload: only the new chunks are indexed and a duplicate adds nothing", async ({ page }) => {
  await login(page);
  await page.goto("/settings");

  const unique = Date.now();
  const file = {
    name: `e2e_case_study_${unique}.md`,
    mimeType: "text/markdown",
    buffer: Buffer.from(
      `# Churn model ${unique}\nTrained scikit-learn and PyTorch models to predict churn for a telecom client and ` +
        `improved retention by 12% using careful model evaluation and MLOps practices ${unique}.`,
    ),
  };

  const card = page.getByRole("region", { name: "Your portfolio" });
  await expect(card.getByTestId("portfolio-counts")).toContainText("built in items");

  await card.locator("#portfolio-files").setInputFiles(file);
  await card.getByRole("button", { name: "Upload and index" }).click();
  const note = card.getByTestId("upload-note");
  await expect(note).toContainText("Added 1 item");
  await expect(note).toContainText("Only 1 new chunk");
  await expect(note).toContainText("were not re-indexed");
  await expect(card.getByText(`Churn model ${unique}`)).toBeVisible();

  // The same file again is recognised, so nothing new is indexed.
  await card.locator("#portfolio-files").setInputFiles(file);
  await card.getByRole("button", { name: "Upload and index" }).click();
  await expect(card.getByTestId("upload-note")).toContainText("Nothing new was added");
  await expect(card.getByTestId("upload-note")).toContainText("already in your portfolio");

  // An unsupported file is refused with a reason.
  await card
    .locator("#portfolio-files")
    .setInputFiles({ name: "tool.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ".repeat(40)) });
  await card.getByRole("button", { name: "Upload and index" }).click();
  await expect(card.getByTestId("upload-note")).toContainText("unsupported type");
});
