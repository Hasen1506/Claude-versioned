// Enterprise 4.2: forecast value add used the guide's way. Input: the sales history and what every forecast release
// kept (naïve, statistical, events and new products, the planners' overrides); processing: each layer judged against
// the sales of the weeks that have sold; output: the error and bias of each layer, per planner and product family,
// the overrides that cost most, and a new release that keeps the next weeks to judge.
import { expect, test, type Page } from "@playwright/test";

const row = (page: Page, table: string, name: RegExp) => page.getByRole("table", { name: table }).getByRole("row", { name });

test("Kaveri's twelve weekly releases: the statistical model against naïve, and Sales West's overrides costing accuracy", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  // input: the kept forecasts, under Data
  await page.goto("/#/data/forecast_snapshots");
  await expect(page.getByText("Sales West").first()).toBeVisible();

  await page.goto("/#/demand/value");
  await expect(page.getByRole("status").filter({ hasText: "Judged on 99 product-weeks that have sold (31,728 units), to Sun 27 Sep" })).toBeVisible({ timeout: 30_000 });
  // over those weeks the statistical model missed by 9.7 %, a little worse than naïve (9.4 %); the overrides added 2.4 points
  await expect(row(page, "Layers", /Naïve/)).toContainText("9.4%");
  await expect(row(page, "Layers", /Statistical model/)).toContainText("−0.3 pts");
  await expect(row(page, "Layers", /consensus/)).toContainText("12.1%");
  await expect(row(page, "Layers", /consensus/)).toContainText("+5.2%");
  await expect(row(page, "Layers", /consensus/)).toContainText("−2.4 pts");
  // per planner: Sales West's quarter lift came closer to the sales twice in twelve and ran 22.6 % high
  await expect(row(page, "By planner", /Sales West/)).toContainText("2 of 12");
  await expect(row(page, "By planner", /Sales West/)).toContainText("−15.4 pts");
  await expect(row(page, "By planner", /Sales West/)).toContainText("+22.6%");
  await expect(row(page, "By planner", /E-commerce desk/)).toContainText("+0.2 pts");
  await expect(row(page, "By product family", /Mixer grinders/)).toContainText("−3.9 pts");
  // the costliest: 686 against 497 sold, where the forecast before the override said 548
  const first = page.getByRole("table", { name: "Costly overrides" }).getByRole("row").nth(1);
  await expect(first).toContainText("Mon 14 Sep");
  await expect(first).toContainText("Mixer grinder 500 W");
  await expect(first).toContainText("138");

  // at phone width the page fits (the tables scroll in their own frame)
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

const snap = (product: string, start: string, end: string, naive: number, statistical: number, adjusted: number, final: number, author = "", overridden = !!author) =>
  ({ location: "CU", product, start, end, made: start, naive, statistical, adjusted, final, author, overridden });
const shop = {
  settings: { company_name: "Value add shop", planning_start: "2026-10-19", horizon_days: 42 },
  locations: [{ id: "CU", name: "Shop", type: "customer" }],
  products: [{ id: "A", name: "Pump", type: "FG", family: "Pumps", price: 10 }, { id: "B", name: "Seal", type: "FG", price: 1 }],
  history: [{ location: "CU", product: "A", date: "2026-09-28", qty: 80 }, { location: "CU", product: "A", date: "2026-10-05", qty: 100 },
    { location: "CU", product: "A", date: "2026-10-12", qty: 60 }, { location: "CU", product: "A", date: "2026-10-14", qty: 50 },
    { location: "CU", product: "B", date: "2026-10-06", qty: 50 }],
  forecasting: { models: ["moving_average"] },
  forecast_snapshots: [
    snap("A", "2026-10-05", "2026-10-12", 80, 90, 95, 120, "ana"), snap("A", "2026-10-12", "2026-10-19", 100, 105, 105, 105),
    snap("B", "2026-10-05", "2026-10-12", 40, 60, 60, 52, "ben"), snap("B", "2026-10-12", "2026-10-19", 50, 10, 10, 10, "", true),
    snap("A", "2026-10-19", "2026-10-26", 110, 110, 110, 110), snap("B", "2026-10-26", "2026-11-02", 0, 5, 5, 5)],
};

test("a small shop judged by hand, then a release keeps the next weeks to judge", async ({ page }) => {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "shop.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(shop)) });
  await expect(page.locator(".topbar .company")).toHaveText("Value add shop");

  await page.goto("/#/demand/value");
  // 260 sold over four product-weeks; absolute misses: naïve 90, statistical 35, events 30, consensus 37
  await expect(page.getByRole("status").filter({ hasText: "Judged on 4 product-weeks that have sold (260 units)" })).toBeVisible({ timeout: 30_000 });
  await expect(row(page, "Layers", /Naïve/)).toContainText("34.6%");
  await expect(row(page, "Layers", /Statistical model/)).toContainText("+21.2 pts");
  await expect(row(page, "Layers", /Events/)).toContainText("+1.9 pts");
  await expect(row(page, "Layers", /consensus/)).toContainText("14.2%");
  await expect(row(page, "Layers", /consensus/)).toContainText("+10.4%");
  await expect(row(page, "Layers", /consensus/)).toContainText("−2.7 pts");
  // ana moved 95 to 120 against 100 sold; ben 60 to 52 against 50; an override without a name counts under "Not named"
  await expect(row(page, "By planner", /ana/)).toContainText("0 of 1");
  await expect(row(page, "By planner", /ana/)).toContainText("−15.0 pts");
  await expect(row(page, "By planner", /ben/)).toContainText("+16.0 pts");
  await expect(row(page, "By planner", /Not named/)).toContainText("0 of 1");
  await expect(page.getByRole("table", { name: "By product family" }).getByRole("row")).toHaveCount(3);
  await expect(page.getByText("2 kept forecasts are for weeks that have not sold yet.")).toBeVisible();

  // processing again: the forecast is used in the supply plan, which keeps every week from the next one on
  await page.getByRole("tab", { name: "Forecast", exact: true }).click();
  const use = page.getByRole("button", { name: "Use this forecast in the supply plan" });
  await expect(use).toBeEnabled({ timeout: 60_000 });
  await use.click();
  await page.getByRole("tab", { name: "Value add" }).click();
  await expect(page.getByText("11 kept forecasts are for weeks that have not sold yet.")).toBeVisible({ timeout: 30_000 });
});
