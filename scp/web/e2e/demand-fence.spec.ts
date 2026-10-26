import { expect, test } from "@playwright/test";

// Enterprise 8.3, supply planning M6 (CONFORMANCE §3), used the guide's way on Kaveri. Input: the 500 W mixer grinder
// at Bhiwandi, whose two customer channels (West trade, e-commerce) follow its strategy; West trade has ordered 450 for
// 1 October. Processing: the planner gives it a demand time fence of 5 working days (Monday 28 September to Saturday
// 3 October). Output: inside the fence only customer orders count: of the forecast left after the orders, 124 at West
// trade and 190.4 at e-commerce are not planned, and the plan says so.
test("inside the demand time fence only customer orders count", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/data/location_products/DC-BHIWANDI%7CMG-500");
  await page.locator("#demand_time_fence_days").fill("5");
  await page.locator("#demand_time_fence_days").blur();
  await page.goto("/#/plan");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  const msgs = page.locator("summary", { hasText: "The engine's messages" });
  await expect(msgs).toBeVisible({ timeout: 45_000 });
  await msgs.click();
  await page.getByRole("button", { name: /^info/ }).click();
  const west = page.getByRole("row").filter({ hasText: "Only orders count this close" }).filter({ hasText: "West trade distributors" });
  await expect(west).toContainText("124 of forecast before Sat 3 Oct not planned: inside the demand time fence only customer orders count");
  await expect(page.getByRole("row").filter({ hasText: "Only orders count this close" }).filter({ hasText: "E-commerce marketplaces" }))
    .toContainText("190.4 of forecast before Sat 3 Oct");
});
