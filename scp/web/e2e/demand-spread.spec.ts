// Enterprise 4.4: demand with a spread and lead times as measured, used the guide's way. Input: past sales, and the
// purchase lines the roll-forward closed; processing: the forecast's interval kept with the forecast, the order check
// run again with the high end of the forecast promised first, and each supplier's receipts against their due dates;
// output: a safe date beside the expected one, and the measured spread planned with in one click, raising safety stock.
import { expect, test, type Page } from "@playwright/test";

async function kaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

test("Kaveri: the forecast's high end used, an order checked for a safe date beside the expected one", async ({ page }) => {
  await kaveri(page);
  // input → processing: the forecast from past sales, with its interval; the high end shown beside the total
  await page.goto("/#/demand");
  await page.getByRole("tab", { name: "Forecast", exact: true }).click();
  await expect(page.getByText(/up to [\d,]+ at the high end \(P90, which about one period in 10 goes over\)/)).toBeVisible({ timeout: 60_000 });
  const use = page.getByRole("button", { name: "Use this forecast in the supply plan" });
  await expect(use).toBeEnabled({ timeout: 60_000 });
  await use.click();
  await expect(page.locator(".banner.info", { hasText: "Released" })).toBeVisible({ timeout: 30_000 });

  // 400 mixer grinders for the north trade on 5 October: Delhi has 300 for that day
  await page.goto("/#/promise/simulate");
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-NORTH-TRADE");
  await page.getByLabel("Product", { exact: true }).selectOption("MG-500");
  await page.getByLabel("Quantity").fill("400");
  await page.getByLabel("Wanted on").fill("2026-10-05");
  await page.getByRole("button", { name: "Check availability" }).click();
  const tiles = page.locator(".grid-auto").first();
  await expect(tiles).toContainText("300 on Mon 5 Oct", { timeout: 30_000 });
  // output: if the other customers order at the high end of their forecast first, fewer of the 300 are left for it
  const high = tiles.locator(".tile", { hasText: "High demand (P90)" });
  await expect(high).toBeVisible();
  const safe = Number((await high.innerText()).match(/([\d,]+) on time/)![1].replace(/,/g, ""));
  expect(safe).toBeGreaterThan(0);
  expect(safe).toBeLessThan(300);
  await expect(page.getByText(/The second answer first promises the [\d,]+ more that other customers would order by Mon 5 Oct if they ordered at the high end/)).toBeVisible();
  await expect(page.getByText("A date given from the first answer may cost an order later; the second is safe to give.")).toBeVisible();

  // the same answer on an order of several lines
  await page.goto("/#/selling/new");
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-NORTH-TRADE");
  await page.getByLabel("Line 10 product").selectOption("MG-500");
  await page.getByLabel("Line 10 quantity").fill("400");
  await page.getByLabel("Line 10 wanted on").fill("2026-10-05");
  await page.getByRole("button", { name: "Check what can be promised" }).click();
  await expect(page.getByLabel("Line 10 can be promised")).toContainText(`If demand runs high (P90): ${safe} on time, the rest by`);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/promise/simulate");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test("Kaveri: Shenzhen's receipts spread ±4 days, planned with in one click, and the switches' safety stock follows", async ({ page }) => {
  await kaveri(page);
  const stage = page.locator("tr", { has: page.getByLabel("Select Rotary switch + PCB at Pune plant (Chakan)") });
  await page.goto("/#/inventory/placement");
  await page.getByRole("button", { name: /Recalculate/ }).first().click();
  // before: 14 days ± 3 from the supplier, with the sea lane's spread, ± 5.8 in all
  await expect(stage).toContainText("± 5.8", { timeout: 60_000 });
  await expect(stage).toContainText("8,647");

  // input: four lines closed from Shenzhen, three a day early and one a week late
  await page.goto("/#/buying/suppliers");
  await page.getByRole("row", { name: /Shenzhen electro-components/ }).click();
  const sw = page.getByRole("row", { name: /PIR-SWITCH/ });
  await expect(sw).toContainText("± 3.0 d");
  await expect(sw).toContainText("± 4.0 d over 4 receipts of all its parts, 1.0 d late on average");
  // output: plan with it
  await sw.getByRole("button", { name: "Plan with ± 4.0 d" }).click();
  await expect(sw.getByRole("button", { name: /Plan with/ })).toHaveCount(0);
  await expect(sw.locator("td").nth(7)).toHaveText("± 4.0 d");
  // the plant's copper wire supplier has delivered two lines so far: nothing measured yet
  await page.getByRole("row", { name: /Hindalco copper/ }).click();
  await expect(page.getByRole("row", { name: /PIR-CU/ })).toContainText("too few receipts yet");

  // the safety stock covers the measured spread: ± 6.4 in all, and more switches held
  await page.goto("/#/inventory/placement");
  await page.getByRole("button", { name: /Recalculate/ }).first().click();
  await expect(stage).toContainText("± 6.4", { timeout: 60_000 });
  await expect(stage).toContainText("9,114");
});
