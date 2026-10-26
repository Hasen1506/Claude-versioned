// Enterprise 5.1: planning again after a change plans only what the change reaches (S/4 net change planning), used the
// guide's way. Input: one stock figure corrected; processing: the plan recalculated from the previous plan's work;
// output: the same plan a full run makes, saying how little of the network it had to plan again.
import { expect, test, type Page } from "@playwright/test";

async function kaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

test("Kaveri: a corrected stock figure is planned again where it reaches, the rest of the plan stands", async ({ page }) => {
  await kaveri(page);

  // input: the heater elements counted at the Pune plant are 20,000, not 14,000
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  const onHand = page.locator('input[id="on_hand"]');
  await expect(onHand).toHaveValue("14000");
  await onHand.fill("20000");
  await onHand.press("Enter");

  // processing: recalculate
  await page.goto("/#/plan");
  await expect(page.getByText("⚠ Out of date")).toBeVisible();
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();

  // output: only the heaters were reached; every other product at every place stands as it was
  const again = page.locator(".again");
  await expect(again).toContainText("Only what the changes since the last plan reached was planned again", { timeout: 30_000 });
  const [, planned, total] = (await again.innerText()).match(/again: ([\d,]+) of ([\d,]+) products/)!;
  expect(Number(planned)).toBeGreaterThan(0);
  expect(Number(planned)).toBeLessThan(Number(total.replace(/,/g, "")) / 2);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/plan");
  await expect(again).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});
