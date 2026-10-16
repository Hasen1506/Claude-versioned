// Enterprise 4.1: the monthly S&OP cycle used the guide's way. Input: the company's budget and plan; processing: the
// five steps signed in order, each freezing the company; output: the plan against the budget step by step, a closed
// month, and a reopened step that reopens the ones after it.
import { expect, test, type Page } from "@playwright/test";

async function openExample(page: Page, name: string) {
  await page.goto("/");
  await page.getByText(name).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const sign = async (page: Page, label: string) => {
  const b = page.getByRole("button", { name: `Sign off ${label}` });
  await expect(b).toBeEnabled({ timeout: 60_000 });
  await b.click();
};

test("a month of S&OP: budget in, five sign-offs, the plan against the budget, then a step reopened", async ({ page }) => {
  test.setTimeout(240_000);    // the supply steps solve the capacity plan
  await openExample(page, "Kaveri Kitchenware");

  // input: the year's budget by product family, under Data
  await page.goto("/#/data/budgets");
  await expect(page.getByText("2026-10").first()).toBeVisible();
  await expect(page.getByText("family Mixer grinders").first()).toBeVisible();

  await page.goto("/#/sop/cycle");
  await expect(page.getByText("No cycle yet")).toBeVisible();
  await page.getByLabel("Cycle month").fill("2026-10");
  await page.getByRole("button", { name: "Start the October 2026 cycle" }).click();
  await expect(page.getByRole("tab", { name: "October 2026 · 0 of 5" })).toBeVisible();

  // 1 data: no blocking problems
  await expect(page.getByText("No blocking problems")).toBeVisible({ timeout: 30_000 });
  await sign(page, "data");

  // 2 demand review: the demand plan month by month against the budget (October: 20,697 against 20,750)
  const months = page.getByRole("table", { name: "Month" });
  await expect(months.getByRole("row", { name: /Oct 2026/ })).toContainText("20,750");
  await expect(months.getByRole("row", { name: /Oct 2026/ })).toContainText("20,697");
  await expect(months.getByRole("row", { name: /Oct 2026/ })).toContainText("−0.3%");
  await expect(page.getByRole("table", { name: "Product family" })).toContainText("Kettles");
  await page.getByRole("button", { name: "Revenue" }).click();
  await expect(months.getByRole("row", { name: /Oct 2026/ })).toContainText("+6.2%");
  await sign(page, "demand review");

  // 3 supply review: the capacity plan solved by month
  await expect(page.getByText(/Supplied: .*100\.0%/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("table", { name: "Month" }).getByRole("columnheader", { name: "Supply plan" })).toBeVisible();
  await sign(page, "supply review");

  // 4 pre-S&OP and 5 the executive meeting take their minutes
  await expect(page.getByRole("button", { name: "Sign off pre-s&op" })).toBeDisabled({ timeout: 60_000 });
  await page.getByLabel("Sign-off note").fill("Kettles below budget in Q1: promotion proposed for January");
  await sign(page, "pre-s&op");
  await expect(page.getByRole("button", { name: "Sign off executive s&op" })).toBeVisible({ timeout: 60_000 });
  await page.getByLabel("Sign-off note").fill("Approved; January kettle promotion goes ahead");
  await sign(page, "executive s&op");

  // output: a closed month, each step kept as a plan version, the plan against the budget step by step
  await expect(page.getByRole("tab", { name: "October 2026 · closed" })).toBeVisible();
  const journey = page.locator("section.panel").filter({ hasText: "Through the month" });
  await expect(journey.getByRole("row")).toHaveCount(5);
  await expect(journey.getByRole("row", { name: /Executive S&OP/ })).toContainText("100.0%");
  await expect(page.getByText("“Approved; January kettle promotion goes ahead”")).toBeVisible();

  // the supply review is reopened: it and the steps after it are open again, their versions stay
  await page.getByRole("button", { name: /Supply review/ }).click();
  await page.getByLabel("Why reopen").fill("Copper supplier cut its November capacity");
  await page.getByRole("button", { name: "Reopen (and the steps after it)" }).click();
  await expect(page.getByRole("tab", { name: "October 2026 · 2 of 5" })).toBeVisible();
  await expect(page.getByText(/reopened: Supply review, Pre-S&OP, Executive S&OP: Copper supplier/)).toBeVisible();
  await expect(journey.getByRole("row", { name: /Supply review \(reopened\)/ })).toBeVisible();

  // the frozen versions are in Versions
  await page.goto("/#/versions");
  await expect(page.getByText("S&OP 2026-10 · Executive S&OP")).toBeVisible();

  // at phone width the cycle fits
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/sop/cycle");
  await expect(page.getByRole("tab", { name: "October 2026 · 2 of 5" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

const small = {
  settings: { company_name: "Cycle company", planning_start: "2026-10-05", horizon_days: 56, default_calendar: "CAL" },
  calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
  locations: [{ id: "P", type: "plant" }, { id: "S", type: "supplier" }],
  products: [{ id: "A", type: "FG", price: 25, family: "Bottles" }],
  location_products: [{ location: "P", product: "A", on_hand: 10, lot_sizing: { policy: "L4L" } }],
  purchasing_sources: [{ id: "BUY-A", supplier: "S", location: "P", product: "A", price: 10, lead_time_days: 1 }],
  demand: [{ id: "F1", location: "P", product: "A", date: "2026-10-12", qty: 100, kind: "forecast" }],
  budgets: [{ month: "2026-10-01", family: "Bottles", qty: 120, revenue: 3000 }],
};

test("in a company kept on the server the owner names step owners from the members, and sign-offs carry the e-mail", async ({ page }) => {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "cycle.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(small)) });
  await expect(page.locator(".topbar .company")).toHaveText("Cycle company");
  const email = `cycle-${Date.now()}-${test.info().workerIndex}@example.invalid`;
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Your name").fill("Cycle owner");
  await page.getByLabel(/^Password/).fill("cycle-owner-20261016");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);

  await page.goto("/#/sop/cycle");
  await page.getByLabel("Cycle month").fill("2026-10");
  await page.getByRole("button", { name: "Start the October 2026 cycle" }).click();
  // the owner select lists the members who may sign
  await page.getByRole("button", { name: /Demand review/ }).click();
  await page.getByLabel("Step owner").selectOption(email);
  await expect(page.getByRole("button", { name: /Demand review/ })).toContainText(email);
  await page.getByRole("button", { name: /^1 Data/ }).click();
  await page.getByRole("button", { name: "Sign off data" }).click();
  await expect(page.getByText(`${email} · signed: Data`)).toBeVisible();
  // the demand review against the budget: the plan starts on 5 October, so 27 of October's 31 days of its budget
  // of 120 count (105), against a demand of 100
  const oct = page.getByRole("table", { name: "Month" }).getByRole("row", { name: /Oct 2026/ });
  await expect(oct).toContainText("from 5 Oct 2026");
  await expect(oct).toContainText("105");
  await expect(oct).toContainText("−4.3%");
  await page.getByRole("button", { name: "Sign off demand review" }).click();
  await expect(page.getByText(`${email} · signed: Demand review`)).toBeVisible();
  await expect(page.getByRole("tab", { name: "October 2026 · 2 of 5" })).toBeVisible();
});
