import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    // a 422 is the engine's typed rejection of invalid values: handled by the UI, not an error
    if (m.type() === "error" && !m.text().includes("status of 422")) errors.push(m.text());
  });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

test("golden path: example → readiness → plan → drill-down → edit → stale → re-plan", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();

  // network map renders every location and traces a product
  await expect(page.locator(".net .node")).toHaveCount(12);
  await page.selectOption('select[aria-label="Trace product"]', "KT-15");
  await expect(page.locator(".net .node.dim").first()).toBeVisible();
  await page.locator(".net .node", { hasText: "PLT-PUNE" }).click();
  await expect(page.getByText("Products planned here")).toBeVisible();

  // readiness passes
  await page.locator('a.nav-item[href="#/readiness"]').click();
  await expect(page.getByText("Ready to plan")).toBeVisible();

  // plan
  const supplyChip = page.locator('.spine a[href="#/plan"] .dot');
  await page.locator('a.nav-item[href="#/plan"]').click();
  await page.getByRole("button", { name: "Run plan" }).click();
  await expect(page.getByText("Total plan cost")).toBeVisible();
  await expect(supplyChip).toHaveClass(/fresh/);
  await expect(page.locator(".tile .value").nth(1)).toContainText("%");

  // node drill-down and pegging
  await page.goto("/#/plan/node/DC-DELHI/MG-750");
  await expect(page.getByText("Stock / requirements by bucket")).toBeVisible();
  await page.locator("tr.clickable", { hasText: "TO-" }).first().click();
  await expect(page.getByRole("heading", { name: "Serves" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Depends on" })).toBeVisible();

  // capacity
  await page.goto("/#/plan/capacity/PUNE-L1");
  await expect(page.getByText("Load by bucket")).toBeVisible();

  // edit an input → plan becomes stale → re-plan → current again
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  const onHand = page.locator('input[id="on_hand"]');
  await onHand.fill("20000");
  await onHand.press("Enter");
  await expect(supplyChip).toHaveClass(/stale/);
  await page.goto("/#/plan");
  await expect(page.getByText("⚠ STALE")).toBeVisible();
  await page.getByRole("button", { name: "Re-plan" }).click();
  await expect(supplyChip).toHaveClass(/fresh/);

  // undo restores the previous value
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator('input[id="on_hand"]')).toHaveValue("14000");
});

test("demand planning: forecast → workbench → consensus override → release → plan stale → undo", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.locator(".net .node")).toHaveCount(12);
  await page.goto("/#/demand");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText("Backtest WAPE")).toBeVisible();
  await expect(page.locator('.spine a[href="#/demand"] .dot')).toHaveClass(/fresh/);

  // workbench: leaderboard with a champion and the cleansing log
  await page.goto("/#/demand/series/CUS-ECOM%7CMG-500");
  await expect(page.getByText("Model leaderboard")).toBeVisible();
  await expect(page.locator("tr.selected").first()).toBeVisible();
  await expect(page.getByText(/History cleansing/)).toBeVisible();

  // consensus grid: type an override, the forecast re-runs with it
  await page.goto("/#/demand/consensus");
  const cell = page.getByLabel(/^KT-15 CUS-ECOM/).first();
  await cell.fill("777");
  await cell.press("Enter");
  await expect(page.locator("td.edit input[value='777']")).toBeVisible();

  // release writes the consensus into forecast demand; undo reverts it
  await page.getByRole("button", { name: "Release to plan" }).click();
  await expect(page.getByText(/forecast records for 9 series/)).toBeVisible();
  await page.goto("/#/data/demand");
  await page.getByLabel("Search").fill("KT-15");
  const released = page.locator("td", { hasText: /^777$/ });
  await expect(released).toHaveCount(1);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(released).toHaveCount(0);
});

test("typed inputs: a percent typed as a fraction is rejected with the field named", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Single-product bottler").click();
  await expect(page.locator(".net .node")).toHaveCount(3);
  await page.goto("/#/settings");
  const wacc = page.locator('input[id="wacc"]');
  await expect(wacc).toHaveValue("12"); // shown as percent, stored as 0.12
  await wacc.fill("1200");
  await wacc.press("Enter");
  await expect(page.getByText("Invalid values", { exact: true })).toBeVisible();
  await page.goto("/#/readiness");
  await expect(page.getByText("settings › wacc")).toBeVisible();
  await page.goto("/#/settings");
  await page.locator('input[id="wacc"]').fill("12");
  await page.locator('input[id="wacc"]').press("Enter");
  await expect(page.getByText("Invalid values", { exact: true })).toHaveCount(0);
});

test("blank network: readiness guides the first steps", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Create blank network" }).click();
  await expect(page.getByRole("heading", { name: "Locations", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /New location/ }).click();
  await expect(page.locator('input[id="id"]')).toHaveValue(/L-\d+/);
  await page.goto("/#/network");
  await expect(page.locator(".net .node")).toHaveCount(1);
});

test("inventory: optimise → placement → approve recommendation → policies change → stale → DDMRP position", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.locator(".net .node")).toHaveCount(12);
  await page.goto("/#/inventory");
  await page.getByRole("button", { name: "Optimise" }).click();
  await expect(page.getByText("Saving vs single-echelon")).toBeVisible();
  await expect(page.locator('.spine a[href="#/inventory"] .dot')).toHaveClass(/fresh/);

  await page.goto("/#/inventory/placement");
  await expect(page.getByRole("img", { name: "Service-time placement per stage" })).toBeVisible();
  await page.getByLabel("Select PLT-PUNE RM-SWITCH").check();
  await page.getByRole("button", { name: /Review 1 change/ }).click();
  await page.getByRole("button", { name: "Approve and apply" }).click();
  await expect(page.locator('.spine a[href="#/inventory"] .dot')).toHaveClass(/stale/);
  await page.getByRole("button", { name: "Re-run" }).click();
  await expect(page.locator('.spine a[href="#/inventory"] .dot')).toHaveClass(/fresh/);
  const row = page.locator("tr", { has: page.getByLabel("Select PLT-PUNE RM-SWITCH") });
  await expect(row.locator("td").nth(10)).toContainText("fixed");

  await page.goto("/#/inventory/ddmrp");
  await page.getByLabel("Show every stocking stage").check();
  await page.getByLabel("Position buffer at DC-DELHI MG-500").check();
  await page.getByRole("button", { name: "Re-run" }).click();
  await page.getByLabel("Show every stocking stage").uncheck();
  await expect(page.getByLabel("Position buffer at DC-DELHI MG-500")).toBeChecked();
});

test("S&OP: solve → pin → cut capacity → shadow prices → release to MRP → undo", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.locator(".net .node")).toHaveCount(12);
  await page.goto("/#/sop");
  await page.getByRole("button", { name: "Solve" }).click();
  await expect(page.getByText("Demand served")).toBeVisible();
  await page.getByRole("button", { name: "Pin this plan as baseline" }).click();

  // scenario: 40 % of the hours → capacity binds and gets a price
  await page.goto("/#/sop/settings");
  const factor = page.locator('input[id="capacity_factor"]');
  await factor.fill("0.4");
  await factor.press("Enter");
  await expect(page.locator('.spine a[href="#/sop"] .dot')).toHaveClass(/stale/);
  await page.goto("/#/sop");
  await page.getByRole("button", { name: "Re-run" }).click();
  await expect(page.locator('.spine a[href="#/sop"] .dot')).toHaveClass(/fresh/);
  await expect(page.getByText(/vs .* plan pinned/).first()).toBeVisible();
  await page.goto("/#/sop/prices");
  await expect(page.locator("td .badge", { hasText: "resource" }).first()).toBeVisible();
  await page.goto("/#/sop/capacity");
  await expect(page.getByText("Value of capacity")).toBeVisible();

  // release the constrained plan: forecast demand is replaced, MRP becomes stale; undo restores it
  await page.goto("/#/sop");
  await page.getByRole("button", { name: "Release to MRP" }).click();
  await expect(page.getByText(/constrained demand records/)).toBeVisible();
  await page.goto("/#/data/demand");
  await page.getByLabel("Search").fill("SOP-");
  await expect(page.locator("td", { hasText: /^SOP-/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator("td", { hasText: /^SOP-/ })).toHaveCount(0);
});
