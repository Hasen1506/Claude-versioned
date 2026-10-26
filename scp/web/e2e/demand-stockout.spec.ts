import { expect, test } from "@playwright/test";

// Enterprise 8.3, demand planning D17 (CONFORMANCE §2), used the guide's way on Kaveri. Input: the 500 W mixer grinder
// sold to West trade distributors, the company's biggest series, whose last two weeks Bhiwandi could not fill: the
// week of 14 September sold out (497 sold) and the week of 21 September turned 120 away (472 sold). Processing: the
// planner marks both in the sales history. Output: the forecast reads them as the demand they were: the first at its
// neighbours' level (522), the second as 472 + 120 = 592, 145 put back and said on the series.
test("weeks out of stock are read as the demand they turned away", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  const mark = async (day: string, edit: (p: typeof page) => Promise<void>) => {
    await page.goto("/#/data/history");
    await page.getByLabel("Search").fill(day);
    await page.getByRole("row").filter({ hasText: "West trade distributors" }).filter({ hasText: "Mixer grinder 500 W" }).first().click();
    await edit(page);
  };
  await mark("2026-09-21", async (p) => { await p.locator("#lost_qty").fill("120"); await p.locator("#lost_qty").blur(); });
  await mark("2026-09-14", async (p) => { await p.locator("#stockout").check(); });
  await page.goto("/#/data/history");
  await page.getByLabel("Search").fill("2026-09-21");
  await expect(page.getByRole("row").filter({ hasText: "West trade distributors" }).filter({ hasText: "Mixer grinder 500 W" }).first())
    .toContainText("120");

  await page.goto("/#/demand/overview");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Backtest WAPE")).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/demand/series/CUS-WEST-TRADE%7CMG-500");
  await expect(page.getByText("2 periods out of stock or with demand turned away: 145 put back")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("□ read as demand (out of stock)")).toBeVisible();
  const log = page.getByRole("row").filter({ hasText: "Out of stock: demand turned away added back" });
  await expect(log).toHaveCount(2);
  await expect(log.filter({ hasText: "W39" })).toContainText("592");
  await expect(log.filter({ hasText: "W38" })).toContainText("522");
});
