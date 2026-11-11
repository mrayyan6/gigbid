import { expect, test } from "@playwright/test";
import { login, setMarketplaceDown } from "./helpers";

test("degraded mode: banner appears when the marketplace is down and clears on recovery", async ({ page, request }) => {
  await login(page);
  await page.goto("/inbox");
  await expect(page.getByTestId("marketplace-banner")).toHaveCount(0);

  try {
    await setMarketplaceDown(request, true);
    const banner = page.getByTestId("marketplace-banner");
    await expect(banner).toBeVisible({ timeout: 20_000 });
    await expect(banner).toContainText("Marketplace unavailable, work is queued");
  } finally {
    await setMarketplaceDown(request, false);
  }
  await expect(page.getByTestId("marketplace-banner")).toHaveCount(0, { timeout: 20_000 });
});
