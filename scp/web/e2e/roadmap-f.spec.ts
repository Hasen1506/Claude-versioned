import { expect, test, type Page } from "@playwright/test";

// Roadmap F (UX audit of 7 Oct 2026, section 4): the exception inbox, ranked by money at risk, grouped by product or
// customer, each row with how the amount was worked out and one action with what it protects and costs.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

test("the exception inbox ranks open exceptions by money at risk, with the basis and one action each", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/tower/inbox");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  const table = page.getByRole("table", { name: "Exception inbox" });
  await expect(table).toBeVisible();
  const rows = table.getByTestId("inbox-row");
  expect(await rows.count()).toBeGreaterThan(3);
  const money = (await rows.locator("td[data-amount]").evaluateAll((tds) => tds.map((td) => Number(td.getAttribute("data-amount")))));
  expect(money[0]).toBeGreaterThan(0);
  expect([...money].sort((a, b) => b - a)).toEqual(money);                 // most money first
  await expect(rows.first()).toContainText(/late × .* selling price|held up ×/);   // how it was worked out
  await expect(rows.first().locator("a.btn")).toBeVisible();                // one action…
  await expect(rows.first()).toContainText(/protects/);                     // …with what it protects
  await expect(page.locator(".tile", { hasText: "Money at risk" })).toBeVisible();
  // the tab says how many are waiting
  const n = await rows.count();
  await expect(page.getByRole("tab", { name: /Problems/ })).toContainText(String(n));
  // the same problems, followed up by owner and age, are one switch away (counted before the switch: the ranked
  // table is gone after it)
  await page.getByRole("radio", { name: "By owner and age" }).click();
  await expect(page.locator(".tile", { hasText: "Open" }).first().locator(".value")).toHaveText(String(n));
});

test("the inbox groups by customer and by product, the group with the most at risk first", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/tower/inbox");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await page.getByLabel("Group by").selectOption("customer");
  const titles = page.locator(".panel h3").filter({ hasText: /at risk$/ });
  await expect(titles.first()).toBeVisible();
  const totals = await page.locator("table[data-total]").evaluateAll((ts) => ts.map((t) => Number(t.getAttribute("data-total"))));
  expect(totals.length).toBeGreaterThan(1);
  expect([...totals].sort((a, b) => b - a)).toEqual(totals);
  await expect(page.getByRole("table", { name: /Exceptions for E-commerce/ })).toBeVisible();
  await page.getByLabel("Group by").selectOption("product");
  await expect(page.getByRole("table", { name: /Exceptions for / }).first()).toBeVisible();
});

test("one click: an action tried on a copy of the plan shows the money at risk before and after, and is kept as one change", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/tower/inbox");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  const table = page.getByRole("table", { name: "Exception inbox" });
  await expect(table).toBeVisible();
  // what needs a person says why it has no one-click version
  const why = table.locator("details", { hasText: "Not in one click: why?" }).first();
  await why.locator("summary").click();
  await expect(why).toContainText(/nothing firm of .* arrives after .*: the late quantity is on planned orders/);
  // overtime on a day over capacity: tried, planned again, the problem is gone
  const overtime = /^Try it: Add .* of overtime/;
  const row = table.getByTestId("inbox-row").filter({ has: page.getByRole("button", { name: overtime }) }).first();
  const tryIt = row.getByRole("button", { name: overtime });
  const before = Number(await row.locator("td[data-amount]").getAttribute("data-amount"));
  await tryIt.click();
  const out = page.getByRole("region", { name: "What this change does" });
  await expect(out).toContainText("Tried on a copy of the plan");
  await expect(out.locator(".tile", { hasText: "This problem" })).toContainText(/→ gone/);
  await expect(out.locator(".tile", { hasText: "All problems" })).toContainText(/less/);
  await expect(out.getByRole("list", { name: "The change" })).toContainText(/h overtime a day instead of/);
  const tile = page.locator(".tile", { hasText: /^Money at risk/ }).first().locator(".value");
  const total = (await tile.textContent())!;
  expect(before).toBeGreaterThan(0);
  // kept: one change, the list is worked out again without it
  await out.getByRole("button", { name: "Keep this change" }).click();
  await expect(out).toHaveCount(0);
  await expect(tile).not.toHaveText(total, { timeout: 30_000 });
  // one change, so one Undo takes it back
  const undo = page.getByRole("button", { name: "Undo", exact: true });
  await expect(undo).toBeEnabled();
  await undo.click();
  await expect(undo).toBeDisabled();
});
