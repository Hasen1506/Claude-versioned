// Enterprise 4.3: planning strategies used the guide's way. Input: how long customers wait for each product, the
// variants that name a planning material and their sales; processing: the strategy advisor against the lead times, and
// one forecast for the variants that their orders use up; output: the advice, the strategy set in one click, and plan
// orders for the planning material that only plan the parts its variants share.
import { expect, test, type Page } from "@playwright/test";

const row = (page: Page, name: RegExp) => page.getByRole("table", { name: "Strategies" }).getByRole("row", { name });

test("Kaveri: the 750 W mixer grinder judged against a ten-day wait, then assembled to order in one click", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  await page.goto("/#/inventory/strategy");
  // two products have a wait set (two days); a day to deliver from Pune, 7.3 to assemble and deliver, 53.3 from scratch
  const status = page.getByRole("status").filter({ hasText: "products judged" });
  await expect(status).toHaveText("2 of 3 products judged: every one meets the wait.", { timeout: 30_000 });
  const mg500 = row(page, /Mixer grinder 500 W/);
  await expect(mg500).toContainText("1 d");
  await expect(mg500).toContainText("7.3 d");
  await expect(mg500).toContainText("53.3 d");
  await expect(mg500).toContainText("Meets the wait");

  // input: customers of the 750 W wait ten days, enough to assemble it but not to get its parts
  const wait = page.getByLabel("Days customers wait for MG-750");
  await wait.fill("10");
  await wait.press("Enter");
  const mg750 = row(page, /Mixer grinder 750 W/);
  await expect(mg750).toContainText("Assemble to order.");
  await expect(mg750).toContainText("Now made to stock, orders using up the forecast, which meets the wait.");
  await expect(status).toHaveText("3 of 3 products judged: every one meets the wait; 1 could be planned another way.");

  // output: planned so in one click, where the strategy for the north trade is read: the Delhi warehouse
  await mg750.getByRole("button", { name: "Assemble to order" }).click();
  await expect(mg750).toContainText("Parts to the forecast, assembled to order");
  await expect(mg750).toContainText("set at Delhi");
  await expect(mg750.getByRole("button")).toHaveCount(0);
  await expect(status).toHaveText("3 of 3 products judged: every one meets the wait.");

  // a wait shorter than the delivery: orders late from stock
  await wait.fill("0.5");
  await wait.press("Enter");
  await expect(mg750).toContainText("Orders late");
  await expect(status).toContainText("1 planned in a way that makes orders late");

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

const weekly = (product: string, qty: number) => Array.from({ length: 16 }, (_, i) => {
  const d = new Date(Date.UTC(2026, 9, 12) - i * 7 * 86_400_000);
  return { location: "CU", product, date: d.toISOString().slice(0, 10), qty };
});
const shop = {
  settings: { company_name: "Variant shop", planning_start: "2026-10-19", horizon_days: 42 },
  locations: [{ id: "P", name: "Plant", type: "plant" }, { id: "S", name: "Supplier", type: "supplier" },
    { id: "CU", name: "Trade", type: "customer" }],
  lanes: [{ id: "L1", origin: "P", destination: "CU", modes: [{ mode: "truck_ftl", transit_days: 2 }] }],
  products: [{ id: "BASE", name: "Mixer", type: "FG" },
    { id: "RED", name: "Mixer red", type: "FG", planning_material: "BASE" },
    { id: "BLUE", name: "Mixer blue twin pack", type: "FG", planning_material: "BASE", planning_factor: 2 },
    { id: "MOTOR", name: "Motor", type: "RM" }],
  production_sources: ["BASE", "RED", "BLUE"].map((p) => ({ id: `M-${p}`, location: "P", product: p, fixed_lead_time_workdays: 1,
    components: [{ product: "MOTOR", qty: p === "BLUE" ? 2 : 1 }] })),
  purchasing_sources: [{ id: "B-MOTOR", location: "P", product: "MOTOR", supplier: "S", lead_time_days: 10, price: 5 }],
  location_products: ["BASE", "RED", "BLUE", "MOTOR"].map((p) => ({ location: "P", product: p, lot_sizing: { policy: "L4L" } })),
  history: [...weekly("RED", 30), ...weekly("BLUE", 10)],
  forecasting: { models: ["moving_average"] },
  demand: [{ id: "SO1", location: "CU", product: "RED", date: "2026-10-27", qty: 30, kind: "sales_order" }],
};

test("a mixer forecast once for its red and blue variants: their sales counted there, their orders using it up", async ({ page }) => {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "shop.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(shop)) });
  await expect(page.locator(".topbar .company")).toHaveText("Variant shop");

  // input: the variant names its planning material and how much of it one uses up
  await page.goto("/#/data/products");
  await expect(page.getByText("Mixer blue twin pack")).toBeVisible();

  // processing: one series for the mixer, from 30 red and 2 × 10 blue a week
  await page.goto("/#/demand/series/CU%7CBASE");
  await expect(page.getByText("Forecast once for its variants (Mixer blue twin pack × 2, Mixer red)")).toBeVisible({ timeout: 60_000 });
  // 50 mixers a week over the six: one product and place, the variants have no forecast of their own
  await expect(page.getByText("Customers are expected to order 300 units over the next 6 weeks, across 1 product and place.")).toBeVisible();
  await page.goto("/#/demand");
  await page.getByRole("tab", { name: "Forecast", exact: true }).click();
  const use = page.getByRole("button", { name: "Use this forecast in the supply plan" });
  await expect(use).toBeEnabled({ timeout: 60_000 });
  await use.click();
  // the release answers before the plan is asked for: a plan asked for sooner is of the demand before it (N290)
  await expect(page.locator(".banner.info", { hasText: "Released" })).toBeVisible({ timeout: 30_000 });

  // output: the mixer's own orders only plan the motors its variants share; the red order is made as itself
  await page.goto("/#/plan/orders");
  await page.getByRole("button", { name: /Recalculate|Calculate/ }).first().click();
  const base = page.locator("tbody tr").filter({ hasText: /^MO-/ }).filter({ has: page.getByRole("cell", { name: "Mixer", exact: true }) });
  await expect(base.first()).toBeVisible({ timeout: 30_000 });
  await expect(base.first()).toContainText("Planning only");
  const red = page.locator("tbody tr").filter({ hasText: /^MO-/ }).filter({ has: page.getByRole("cell", { name: "Mixer red", exact: true }) });
  await expect(red.first()).toBeVisible();
  await expect(red.first()).not.toContainText("Planning only");
});
