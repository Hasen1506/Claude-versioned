import { expect, test, type Page } from "@playwright/test";

// Enterprise 8.5, N363: the second working day, the jobs the first one (persona-day.spec.ts) left out. Kaveri on Mon
// 28 Sep, four people in turn, each starting from Home's work waiting and moving only by what the screens offer. The
// demand planner looks at the forecasts that keep missing and puts the forecast in the plan; the planner pushes out an
// order that comes too early; the order desk takes a customer's order; the scheduler compares the rules, picks critical
// ratio and gives the orders the schedule's dates.
test.describe.configure({ mode: "serial" });

let page: Page;
const home = async () => {
  await page.locator("#main-nav").getByRole("link", { name: "Home", exact: true }).click();
  await expect(page.getByRole("region", { name: "Work waiting, by job" })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 90_000 });
};
const work = (job: string) => page.getByRole("region", { name: "Work waiting, by job" }).getByLabel(`${job} work`);

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 90_000 });
});

test.afterAll(async () => { await page.close(); });

test("the demand planner: the forecasts that keep missing, one opened, then the forecast put in the plan", async () => {
  test.setTimeout(180_000);
  await home();
  // five of nine series past the tracking signal's ±4 (value-add.spec.ts works them out)
  await work("Demand").getByRole("link", { name: "5 forecasts that keep missing one way" }).click();
  await expect(page.getByRole("tab", { name: /Value add/, selected: true })).toBeVisible();
  await expect(page.getByText("5 of 9 series are biased.")).toBeVisible({ timeout: 30_000 });
  const first = page.getByRole("table", { name: "Tracking signal" }).getByRole("row").nth(1);
  await expect(first).toContainText("forecast too high");
  await first.getByRole("link", { name: "Mixer grinder 750 W" }).click();
  await expect(page.getByText("Model leaderboard")).toBeVisible({ timeout: 30_000 });

  await page.getByRole("tab", { name: "Forecast", exact: true }).click();
  const use = page.getByRole("button", { name: "Use this forecast in the supply plan" });
  await expect(use).toBeEnabled({ timeout: 60_000 });
  await use.click();
  await expect(page.getByText(/forecast records for \d+ series written to demand/)).toBeVisible({ timeout: 45_000 });
  await home();
  await expect(work("Demand")).not.toContainText("changed since");
});

test("the planner: an order that comes before it is needed, pushed out in one click", async () => {
  test.setTimeout(180_000);
  await home();
  await work("Planning").getByRole("link", { name: /problems? on the follow-up list/ }).click();
  const table = page.getByRole("table", { name: "Exception inbox" });
  await expect(table).toBeVisible({ timeout: 45_000 });
  // MO-100455, 500 W grinders at Pune, arrives Wed 30 Sep; nothing needs them before Sat 10 Oct (N366)
  const row = table.getByTestId("inbox-row").filter({ hasText: "MO-100455" }).first();
  await row.getByRole("button", { name: /^Try it: Push out the receipt/ }).click();
  const out = page.getByRole("region", { name: "What this change does" });
  await expect(out).toContainText("Tried on a copy of the plan", { timeout: 45_000 });
  await expect(out.locator(".tile", { hasText: "This problem" })).toContainText(/→ gone/);
  await expect(out.getByRole("list", { name: "The change" })).toContainText("MO-100455: due Sat 10 Oct instead of Wed 30 Sep (the date it is first needed)");
  await out.getByRole("button", { name: "Keep this change" }).click();
  await expect(out).toHaveCount(0);
  await expect(table.getByTestId("inbox-row").filter({ hasText: "MO-100455" })).toHaveCount(0, { timeout: 45_000 });
});

test("the order desk: the order not confirmed for its date, then a new customer order taken", async () => {
  test.setTimeout(180_000);
  await home();
  await work("Order desk").getByRole("link", { name: /customer orders? not confirmed for the date asked/ }).click();
  await expect(page.getByRole("tab", { name: /Sales orders/, selected: true })).toBeVisible();

  await page.getByRole("tab", { name: "New order" }).click();
  await page.getByLabel("Quantity").fill("40");
  await page.getByLabel("Customer's order number").fill("PO-9120");
  await page.getByRole("button", { name: "Check availability" }).click();
  await page.getByRole("button", { name: "Take this order" }).click();
  await expect(page.locator(".banner.info", { hasText: "Saved" })).toContainText(/SO-88222 taken: 40 /, { timeout: 45_000 });
  await expect(page.locator("tr", { hasText: "SO-88222" }).first()).toContainText("PO-9120");
});

test("the scheduler: the late orders, every rule compared, critical ratio chosen and its dates used", async () => {
  test.setTimeout(240_000);
  await home();
  await work("Production").getByRole("link", { name: /orders? the shop floor schedule finishes late/ }).click();
  await expect(page.getByRole("tab", { name: "Planning board", selected: true })).toBeVisible();

  await page.getByRole("tab", { name: "Methods & profiles" }).click();
  await page.getByRole("button", { name: "Compare all methods" }).click();
  const cmp = page.locator("section.panel", { hasText: "Compare the methods" });
  const cr = cmp.locator("tr", { has: page.getByText("Critical ratio", { exact: true }) });
  await expect(cr).toBeVisible({ timeout: 90_000 });
  await cr.getByRole("button", { name: "Use this" }).click();
  await expect(cr).toContainText("in use", { timeout: 60_000 });

  await page.getByRole("tab", { name: "Planning board" }).click();
  await expect(page.locator(".tile", { hasText: "Sequence" })).toContainText("Critical ratio", { timeout: 60_000 });
  await page.getByRole("button", { name: "Use these dates in the plan" }).click();
  await page.getByRole("alertdialog", { name: "Use the schedule's dates" }).getByRole("button", { name: "Use the dates" }).click();
  await expect(page.getByText(/became production orders with the schedule's dates/)).toBeVisible({ timeout: 60_000 });
});
