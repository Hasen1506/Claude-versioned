import { expect, test } from "@playwright/test";

// Enterprise 8.2, used the guide's way on Kaveri. Input: the company as it ships, its safety stock set product by
// product. Processing: the planner finds Inventory policy from the menu, reads each product's class, rule, target and
// the service achieved, then gives the AX class its suggested target in one step. Output: the targets below their
// class are gone, the Bhiwandi mixer grinder holds more safety stock for 98 % instead of 97 %, and the products whose
// safety stock is in days of cover are named as left alone. Engine: scp/inventory/policy.

const first = (t: string) => Number(t.split("\n")[0].replace(/[^\d.-]/g, ""));

test("each product's policy in one table, a class given its suggested target in one step", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  // found from the menu: Supply, then its Inventory policy tab
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Supply", exact: true }).click();
  await page.getByRole("navigation", { name: "Supply pages" }).getByRole("link", { name: "Inventory policy" }).click();
  await expect(page.getByRole("heading", { name: "Inventory policy" })).toBeVisible();

  // input read back: the Bhiwandi 500 W mixer grinder, class AX, its own 97 % against the class's 98 %, and what it achieved
  const table = page.getByRole("table", { name: "Inventory policy" });
  const row = table.getByRole("row", { name: /Mixer grinder 500 ?W.*Bhiwandi/ }).first();
  await expect(row).toContainText("AX");
  await expect(row).toContainText("97.0% cycle");
  await expect(row).toContainText("class AX suggests 98%");
  // measured as the target is set (N359): Bhiwandi received nothing in the window, so its cycles are not told apart
  await expect(row).toContainText("cycles not measured");
  await expect(row).toContainText("4 of 9 orders on time");
  await expect(page.locator(".tile", { hasText: "Short of their target" })).toContainText("6 not measured (no receipt in the window)");
  const before = first(await row.locator("td").nth(4).innerText());
  const below = page.locator(".tile", { hasText: "Below their class" }).locator(".value");
  await expect(below).toHaveText("4");

  // processing: the AX class given its suggestion in one step
  await page.getByRole("table", { name: "Classes" }).getByRole("row", { name: /^AX/ }).click();
  await expect(page.getByText("For every product in class AX (11).")).toBeVisible();
  await page.getByRole("checkbox", { name: "its class's suggestion" }).check();
  await page.getByRole("button", { name: "Apply to 11 products" }).click();

  // output: five targets set, the six whose safety stock is not set by a target named, none below its class
  const done = page.getByRole("status").filter({ hasText: "Set 5 service targets on 11 products at places" });
  await expect(done).toBeVisible({ timeout: 30_000 });
  await expect(done).toContainText("Left as they were, safety stock not set by a service target: Mixer grinder 500 W at Pune plant (Chakan),");
  await expect(below).toHaveText("0");
  const after = table.getByRole("row", { name: /Mixer grinder 500 ?W.*Bhiwandi/ }).first();
  await expect(after).toContainText("98.0% cycle");
  expect(first(await after.locator("td").nth(4).innerText())).toBeGreaterThan(before);
  await page.screenshot({ path: "test-results/inventory-policy.png", fullPage: true });
});

// Enterprise 8.2, periodic review (CONFORMANCE I7). Input: Kaveri's class CX (the Delhi kettle, the mixer body and
// both cartons at Pune), planned by time-phased MRP. Processing: the class is put on a reorder point reviewed every
// 7 days in one step. Output: each reads as (R, s, Q) with its first review on Monday 28 September and a reorder point
// from its demand, lead time, review and safety stock; the plan then orders them on review days (engine test_policy).
test("a class put on a weekly reorder point in one step", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/policy");
  await expect(page.getByRole("heading", { name: "Inventory policy" })).toBeVisible();
  const table = page.getByRole("table", { name: "Inventory policy" });
  const carton = table.getByRole("row", { name: /Carton.*Pune/ }).first();
  await expect(carton).toContainText("Time-phased (MRP)");

  await page.getByRole("table", { name: "Classes" }).getByRole("row", { name: /^CX/ }).click();
  await page.getByRole("combobox", { name: "Rule" }).selectOption("reorder_point");
  await page.getByRole("textbox", { name: "Review period in days" }).fill("7");
  await page.getByRole("button", { name: "Apply to 4 products" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Set 4 review periods, 4 rules, 4 reorder points on 4 products at places." }))
    .toBeVisible({ timeout: 30_000 });
  await expect(carton).toContainText("Periodic review, reorder point, fixed quantity (R, s, Q)");
  await expect(carton).toContainText("reviewed every 7 days, next on Mon 28 Sep");
  await expect(carton.locator("td").nth(6)).not.toContainText("—");
});

// Enterprise 8.2, safety stock for demand that varies widely (CONFORMANCE I18), on the Chennai pump case. Input: the
// 5 HP pump at Sriperumbudur, 15.6 a day over a 1.2-day lead time with a weekly CV of 0.25: over the lead time a mean
// of 18.2 and σ 11.1, a CV of 0.61. Processing: the page says a normal spread fits poorly and what a gamma one would
// hold; the planner gives it a gamma spread. Output: its 95 % target now holds 21.3 instead of 18.3.
test("demand that varies widely is named and sized by a gamma spread", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByRole("button", { name: /Example case: Coromandel Pumps, Chennai \(fictional\)/ }).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/policy");
  const table = page.getByRole("table", { name: "Inventory policy" });
  const pump = table.getByRole("row", { name: /Farm monoblock pump 5 HP.*Sriperumbudur/ }).first();
  await expect(pump).toContainText("varies widely (CV 0.61), which a normal spread fits poorly: spread as a gamma, the target needs 21 instead of 18");
  await expect(pump.locator("td").nth(4)).toContainText("18");

  await pump.getByRole("checkbox").check();
  await page.getByRole("combobox", { name: "Demand spread" }).selectOption("gamma");
  await page.getByRole("button", { name: "Apply to 1 product" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Set 1 demand spread on 1 product at a place." })).toBeVisible({ timeout: 30_000 });
  await expect(pump.locator("td").nth(4)).toContainText("gamma spread");
  expect(first(await pump.locator("td").nth(4).innerText())).toBeCloseTo(21.3, 0);
  await expect(pump).not.toContainText("varies widely");
});
