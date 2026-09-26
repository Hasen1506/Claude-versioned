import { expect, test, type Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    // a 422 is the engine's typed rejection of invalid values, a 409 its refusal of an action the data doesn't allow
    // (e.g. receiving beyond the supplier's tolerance): both are shown on the page, not errors
    if (m.type() === "error" && !/status of (422|409)/.test(m.text())) errors.push(m.text());
  });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

/** Open an example. It plans itself on opening, so wait until every result is calculated. */
async function openExample(page: Page, name: string) {
  await page.goto("/");
  await page.getByText(name).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

/** A page's freshness, as the rail (or its section's tabs) shows it. */
const freshness = (page: Page, id: string) => page.locator(`.rail a[href="#/${id}"], .section-tabs a[href="#/${id}"]`).first();

test("golden path: example opens planned → home → network → data check → plan → drill-down → edit → out of date → re-plan", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");

  // home answers first, with links to where you act
  await expect(page.getByRole("heading", { name: /^Plan for / })).toBeVisible();
  await expect(page.getByRole("region", { name: "Will customers get what they need?" })).toContainText("% on time");
  await expect(page.getByRole("region", { name: "What to do this week" })).toContainText(/orders? start by/);
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh");

  // network map renders every location and traces a product
  await page.locator('.rail a[href="#/network"]').click();
  await expect(page.locator(".net .node")).toHaveCount(12);
  await page.selectOption('select[aria-label="Trace product"]', "KT-15");
  await expect(page.locator(".net .node.dim").first()).toBeVisible();
  await page.locator(".net .node", { hasText: "PLT-PUNE" }).click();
  await expect(page.getByText("Products planned here")).toBeVisible();

  // the data check passes
  await page.locator('.section-tabs a[href="#/readiness"]').click();
  await expect(page.getByText("Ready to plan")).toBeVisible();

  // plan (already calculated on opening); re-planning keeps it current
  await page.locator('.rail a[href="#/plan"]').click();
  await expect(page.getByText("Total plan cost")).toBeVisible();
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh");
  await expect(page.locator(".tile .value").nth(0)).toContainText("%");

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
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "stale");
  await page.goto("/#/plan");
  await expect(page.getByText("⚠ Out of date")).toBeVisible();
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh");

  // undo restores the previous value
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator('input[id="on_hand"]')).toHaveValue("14000");
});

test("demand planning: forecast → workbench → consensus override → release → plan stale → undo", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/demand/overview");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Backtest WAPE")).toBeVisible();
  await expect(freshness(page, "demand")).toHaveAttribute("data-fresh", "fresh");

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
  await page.getByRole("button", { name: "Use this forecast in the supply plan" }).click();
  await expect(page.getByText(/forecast records for 9 series/)).toBeVisible();
  await page.goto("/#/data/demand");
  await page.getByLabel("Search").fill("KT-15");
  const released = page.locator("td", { hasText: /^777$/ });
  await expect(released).toHaveCount(1);
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(released).toHaveCount(0);
});

test("typed inputs: a percent typed as a fraction is rejected with the field named", async ({ page }) => {
  await openExample(page, "Single-product bottler");
  await page.goto("/#/settings");
  const wacc = page.locator('input[id="wacc"]');
  await expect(wacc).toHaveValue("12"); // shown as percent, stored as 0.12
  await wacc.fill("1200");
  await wacc.press("Enter");
  await expect(page.getByText("Invalid values", { exact: true })).toBeVisible();
  await page.goto("/#/readiness");
  await expect(page.getByText("WACC must be 100% or less")).toBeVisible();
  await page.goto("/#/settings");
  await page.locator('input[id="wacc"]').fill("12");
  await page.locator('input[id="wacc"]').press("Enter");
  await expect(page.getByText("Invalid values", { exact: true })).toHaveCount(0);
});

test("blank network: the checklist and guided setup take a planner from nothing to a plan", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Start with an empty company" }).click();
  await expect(page.getByText("Nothing to plan yet: the network is empty.")).toBeVisible();
  await page.getByRole("link", { name: "Set up the network" }).click();
  await expect(page.getByRole("heading", { name: "Places and routes" })).toBeVisible();
  const place = async (name: string, type: string) => {
    await page.getByPlaceholder("e.g. Pune plant").fill(name);
    await page.locator("label.qf", { hasText: "What it is" }).locator("select").selectOption(type);
    await page.getByRole("button", { name: "Add place" }).click();
  };
  await place("Supplier A", "supplier");
  await place("Pune plant", "plant");
  await place("Mumbai DC", "dc");
  // connect two places on the map
  await page.getByRole("button", { name: "Pune plant (Plant)" }).click();
  await page.getByRole("button", { name: "Mumbai DC (Distribution centre)" }).click();
  await page.getByRole("button", { name: "Add route" }).click();
  await expect(page.getByLabel("Days from Pune plant to Mumbai DC")).toHaveValue("2");

  // a product, made at the plant from a new part on a new line; the part bought from the supplier
  await page.goto("/#/setup/products");
  await page.getByPlaceholder("e.g. Oil filter").fill("Oil filter");
  await page.getByRole("button", { name: "Add product" }).click();
  await page.goto("/#/setup/product/OIL-FILTER/PUNE-PLANT");
  await page.getByRole("button", { name: "Make it here" }).click();
  await page.getByRole("button", { name: "+ Add a part" }).click();
  const make = page.locator(".wz-card.attn .wz-form").first();
  await make.locator("label.qf", { hasText: "Part" }).first().locator("select").selectOption("+new");
  await make.locator("label.qf", { hasText: "New part's name" }).locator("input").fill("Filter media");
  await make.locator("label.qf", { hasText: "Quantity per unit" }).locator("input").fill("2");
  await page.getByRole("button", { name: "+ Add a step" }).click();
  await make.locator("label.qf", { hasText: "Its name" }).locator("input").fill("Line 1");
  await make.getByRole("button", { name: "Save" }).click();
  await page.getByRole("link", { name: "Set it up" }).click();
  await page.getByRole("button", { name: "Buy it" }).click();
  const buy = page.locator(".wz-card.attn .wz-form").first();
  await buy.locator("label.qf", { hasText: "Price per unit" }).locator("input").fill("40");
  await buy.getByRole("button", { name: "Save" }).click();

  // the checklist now asks only for demand; typing it into the demand plan makes the company ready
  await page.goto("/#/readiness");
  await expect(page.getByText("Nothing to plan yet: no product has any demand.")).toBeVisible();
  await page.goto("/#/demand");
  await page.getByLabel("Product", { exact: true }).selectOption({ label: "Oil filter" });
  await page.getByLabel("Place", { exact: true }).selectOption({ label: "Pune plant" });
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const week = page.locator("input.dp-in").nth(1);
  await week.fill("500");
  await week.press("Enter");
  await page.goto("/#/readiness");
  await expect(page.getByText("Ready to plan")).toBeVisible();
  await page.goto("/#/network");
  await expect(page.locator(".net .node")).toHaveCount(3);
});

test("an unfinished record is set aside, not a lock on the whole company", async ({ page }) => {
  await openExample(page, "Single-product bottler");
  await page.goto("/#/data/lanes");
  await page.getByRole("button", { name: /New lane/ }).click();
  await expect(page.getByText(/is left out of planning until it is fixed: from is not filled in/)).toBeVisible();
  await page.goto("/#/plan");
  await page.getByRole("button", { name: /Recalculate|Calculate/ }).first().click();
  await expect(page.getByText(/of demand is covered on time/)).toBeVisible();
});

test("inventory: optimise → placement → approve recommendation → policies change → stale → DDMRP position", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/inventory");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Saving vs single-echelon")).toBeVisible();
  await expect(freshness(page, "inventory")).toHaveAttribute("data-fresh", "fresh");

  await page.goto("/#/inventory/placement");
  await expect(page.getByRole("img", { name: "Service-time placement per stage" })).toBeVisible();
  await page.getByLabel("Select PLT-PUNE RM-SWITCH").check();
  await page.getByRole("button", { name: /Review 1 change/ }).click();
  await page.getByRole("button", { name: "Use these buffers in the plan" }).click();
  await expect(freshness(page, "inventory")).toHaveAttribute("data-fresh", "stale");
  await page.getByRole("button", { name: "Recalculate now" }).click();
  await expect(freshness(page, "inventory")).toHaveAttribute("data-fresh", "fresh");
  const row = page.locator("tr", { has: page.getByLabel("Select PLT-PUNE RM-SWITCH") });
  await expect(row.locator("td").nth(10)).toContainText("fixed");

  await page.goto("/#/inventory/ddmrp");
  await page.getByLabel("Show every stocking stage").check();
  await page.getByLabel("Position buffer at DC-DELHI MG-500").check();
  await page.getByRole("button", { name: "Recalculate now" }).click();
  await page.getByLabel("Show every stocking stage").uncheck();
  await expect(page.getByLabel("Position buffer at DC-DELHI MG-500")).toBeChecked();
});

test("S&OP: solve → pin → cut capacity → shadow prices → release to MRP → undo", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/sop");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Demand served")).toBeVisible();
  await page.getByRole("button", { name: "Pin this plan as baseline" }).click();

  // scenario: 40 % of the hours → capacity binds and gets a price
  await page.goto("/#/sop/settings");
  const factor = page.locator('input[id="capacity_factor"]');
  await factor.fill("0.4");
  await factor.press("Enter");
  await expect(freshness(page, "sop")).toHaveAttribute("data-fresh", "stale");
  await page.goto("/#/sop");
  await page.getByRole("button", { name: "Recalculate now" }).click();
  await expect(freshness(page, "sop")).toHaveAttribute("data-fresh", "fresh");
  await expect(page.getByText(/vs .* plan pinned/).first()).toBeVisible();
  await page.goto("/#/sop/prices");
  await expect(page.locator("td .badge", { hasText: "resource" }).first()).toBeVisible();
  await page.goto("/#/sop/capacity");
  await expect(page.getByText("Value of capacity")).toBeVisible();

  // release the constrained plan: forecast demand is replaced, MRP becomes stale; undo restores it
  await page.goto("/#/sop");
  await page.getByRole("button", { name: "Use this plan in the supply plan" }).click();
  await expect(page.getByText(/constrained demand records/)).toBeVisible();
  await page.goto("/#/data/demand");
  await page.getByLabel("Search").fill("SOP-");
  await expect(page.locator("td", { hasText: /^SOP-/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator("td", { hasText: /^SOP-/ })).toHaveCount(0);
});

test("scheduling: schedule → select order → resequence → reset → edit setup matrix → stale", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/schedule");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Orders scheduled")).toBeVisible();
  await expect(freshness(page, "schedule")).toHaveAttribute("data-fresh", "fresh");
  await expect(page.locator(".gantt svg g[data-order]").first()).toBeVisible();

  // follow an order across resources, then push it one place later on its first resource
  await page.locator('.gantt svg g[data-order="MO-00024"]').first().dispatchEvent("click");
  await expect(page.getByText("MO-00024 · MG-500")).toBeVisible();
  await page.getByRole("button", { name: "later ▶" }).first().click();
  await expect(page.getByText("Your sequence")).toBeVisible();
  await page.getByRole("button", { name: "Undo my changes to the order" }).click();
  await expect(page.getByText("Your sequence")).toHaveCount(0);

  await page.goto("/#/schedule/orders");
  await expect(page.locator("td", { hasText: "MO-100455" })).toBeVisible();

  // the setup matrix edits the dataset: the schedule goes stale
  await page.goto("/#/schedule/setups");
  await page.getByRole("button", { name: "PUNE-TEST" }).click();
  const cell = page.getByLabel("KT to MG hours");
  await cell.fill("3");
  await cell.press("Enter");
  await expect(freshness(page, "schedule")).toHaveAttribute("data-fresh", "stale");
  await page.goto("/#/data/changeovers");
  await expect(page.locator("td", { hasText: /^3$/ }).first()).toBeVisible();
});

test("shop floor methods: compare every method → pick a profile → drag a step on the board → undo", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/schedule/methods");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByRole("button", { name: /Balanced/ })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("cell", { name: "Campaigns by setup group" })).toBeVisible();   // the catalogue

  // every method on the same orders; the optimiser starts from the local search, so it is never worse
  await page.getByRole("button", { name: "Compare all methods" }).click();
  const cmp = page.locator("section.panel", { hasText: "Compare the methods" });
  const row = (name: string) => cmp.locator("tr", { has: page.getByText(name, { exact: true }) });
  await expect(row("Optimiser (constraint solver)")).toBeVisible({ timeout: 60_000 });
  await expect(cmp.locator("tbody tr .badge", { hasText: "best" })).toHaveCount(1);
  const score = async (name: string) => Number(await row(name).locator("td").nth(5).innerText());
  expect(await score("Optimiser (constraint solver)")).toBeLessThanOrEqual(await score("Local search"));

  // a profile is one click; the board says how the schedule was found; Undo puts the settings back
  await page.getByRole("button", { name: /Best possible \(optimiser\)/ }).click();
  await expect(page.getByRole("button", { name: /Best possible/ })).toHaveAttribute("aria-pressed", "true", { timeout: 60_000 });
  await expect(freshness(page, "schedule")).toHaveAttribute("data-fresh", "fresh", { timeout: 60_000 });
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh");   // only the shop floor reads its settings
  await page.getByRole("tab", { name: "Planning board" }).click();
  await expect(page.locator(".tile", { hasText: "Sequence" })).toContainText(/Optimiser|Local search/);

  // drag a step along its row: the schedule is re-timed with it there
  const bar = page.locator('.gantt svg g[data-order] rect').nth(3);
  const box = (await bar.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2, { steps: 6 });
  await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2, { steps: 6 });
  await page.mouse.up();
  await expect(page.getByText("Your sequence")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/step \d+ moved.*Late orders \d+ → \d+/)).toBeVisible();
  await page.getByRole("button", { name: "Undo my changes to the order" }).click();
  await expect(page.getByText("Your sequence")).toHaveCount(0, { timeout: 60_000 });
});

test("promising: check → CTP simulation → commit → supply shrinks → at risk → BOP → commit", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/promise");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Orders on time")).toBeVisible();
  await expect(page.locator("tr", { hasText: "SO-88221" }).locator(".badge", { hasText: "late" })).toBeVisible();   // allocation pushes 200 out

  // a big new order: ATP covers part, capable-to-promise quotes the rest through production
  await page.goto("/#/promise/simulate");
  await page.locator("select").nth(1).selectOption("MG-750");
  await page.locator('input[type="number"]').first().fill("6000");
  await page.getByRole("button", { name: "Check availability" }).click();
  await expect(page.getByText("How the new supply gets there")).toBeVisible();
  await expect(page.getByText("capable-to-promise").first()).toBeVisible();

  // commit, then take planned receipts out of the scope: committed promises are no longer covered
  await page.goto("/#/promise");
  await page.getByRole("button", { name: "Save these promised dates" }).click();
  await expect(page.getByText(/schedule lines committed/)).toBeVisible();
  await page.goto("/#/promise/settings");
  await page.locator('input[id="include_planned_orders"]').uncheck();
  await expect(freshness(page, "promise")).toHaveAttribute("data-fresh", "stale");
  await page.goto("/#/promise");
  await page.getByRole("button", { name: "Recalculate now" }).click();
  await expect(page.getByText(/promises at risk/)).toBeVisible();

  await page.getByRole("link", { name: "Open BOP" }).click();
  await page.getByRole("button", { name: "Re-decide who gets scarce stock" }).click();
  await expect(page.locator("td .badge", { hasText: "lost" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Save these new promised dates" }).click();
  await expect(page.getByText(/schedule lines committed/)).toBeVisible();
  await page.goto("/#/promise");
  await expect(page.getByText(/promises at risk/)).toHaveCount(0);
});

test("execution: journal → stock in sync → ship → roll forward → accuracy → firm planned orders", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/execution");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("On-hand reconciliation")).toBeVisible();
  await expect(page.locator(".tile", { hasText: "Out of sync" }).locator(".value")).toHaveText("0");

  // deliver the rest of SO-88190 inside the coming week
  await page.goto("/#/execution/orders");
  await page.locator('input[id="post-date"]').fill("2026-10-03");
  await page.getByRole("button", { name: "Ship SO-88190" }).click();
  await expect(freshness(page, "execution")).toHaveAttribute("data-fresh", "stale");

  // roll one week: orders close, the week is measured
  await page.goto("/#/execution/roll");
  await page.getByRole("button", { name: "Move the plan to this date" }).click();
  await expect(page.getByText("Rolled from")).toBeVisible();
  await expect(page.locator(".tile", { hasText: "Orders closed" }).locator(".value")).toHaveText("4");
  await page.goto("/#/execution/accuracy");
  await expect(page.getByText("Weeks measured")).toBeVisible();
  await expect(page.locator(".tile", { hasText: "Forecast accuracy" }).locator(".value")).toContainText("%");

  // firm the planned orders inside the firm zone
  await page.goto("/#/execution/orders");
  await page.getByRole("button", { name: /^(Recalculate the supply plan|Calculate the supply plan)$/ }).click();
  await page.getByRole("button", { name: /^Make \d+ orders? firm$/ }).click();
  await expect(page.getByText(/planned orders firmed/)).toBeVisible();
  await expect(page.locator("td", { hasText: /^PRD-\d{5}$/ }).first()).toBeVisible();
});

test("buying: requisitions → purchase order → approve → send → confirm late and short → plan warns → receive part → block a supplier → undo", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/buying");
  await expect(page.locator(".stage-head .answer")).toContainText("should be ordered in the next 7 days");
  await expect(page.getByRole("row", { name: /Stainless jar set/ })).toContainText("Rajkot jar works");

  // one order to the jar supplier, above the approval limit
  await page.getByRole("button", { name: /^Create purchase orders \(1\)$/ }).click();
  await expect(page.locator(".banner.ok")).toContainText("needs approval");
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh");       // re-planned: nothing to buy twice
  await page.getByRole("tab", { name: /Purchase orders/ }).click();
  await page.locator("tr.clickable", { hasText: "Rajkot jar works" }).click();
  await expect(page.getByRole("button", { name: "Mark as sent" })).toHaveCount(0);      // not before approval
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Mark as sent" }).click();
  await expect(page.locator(".banner.ok")).toContainText("sent to SUP-JARS");

  // the supplier confirms four days late and 300 short: the plan expects that, and says so
  await page.getByRole("button", { name: "Record confirmation" }).click();
  await page.getByLabel(/Confirmed date/).fill("2026-10-19");
  await page.getByLabel(/Confirmed quantity/).fill("4000");
  await page.getByRole("button", { name: "Save confirmation" }).click();
  await expect(page.locator(".banner.ok")).toContainText("the plan now counts only what is confirmed");
  await page.goto("/#/plan");
  await expect(page.getByText(/purchase order line confirmed later than asked/)).toBeVisible();
  await expect(page.getByText(/purchase order line confirmed for less than ordered/)).toBeVisible();

  // a first delivery; more than the tolerance is refused
  await page.goto("/#/buying/orders");
  await page.locator("tr.clickable", { hasText: "Rajkot jar works" }).click();
  await page.getByRole("button", { name: "Receive goods" }).click();
  await page.getByLabel(/Receive quantity/).fill("9000");
  await page.getByRole("button", { name: "Post goods receipt" }).click();
  await expect(page.locator(".banner.error")).toContainText("over-delivery tolerance");
  await page.getByLabel(/Receive quantity/).fill("1500");
  await page.getByRole("button", { name: "Post goods receipt" }).click();
  await expect(page.locator(".banner.ok")).toContainText("2,800 still to come");
  await expect(page.locator("tr.clickable", { hasText: "Rajkot jar works" })).toContainText("partly received");

  // scorecard, then a purchasing block takes the supplier out of planning
  await page.getByRole("tab", { name: /Suppliers/ }).click();
  await page.locator("tr.clickable", { hasText: "Shenzhen electro-components" }).click();
  await expect(page.getByText("their no. HT-220-1K2")).toBeVisible();
  await page.locator("tr.clickable", { hasText: "Hindalco copper" }).click();
  await expect(page.getByText(/from 2,000: ₹890/)).toBeVisible();
  await page.getByRole("button", { name: "Block for purchasing" }).click();
  await expect(freshness(page, "buying")).toHaveAttribute("data-fresh", "stale");
  await page.goto("/#/readiness");
  await expect(page.getByText(/only purchasing sources are blocked \(PIR-CU\)/)).toBeVisible();
  await page.getByRole("button", { name: "Undo" }).first().click();
  await expect(page.getByText(/only purchasing sources are blocked/)).toHaveCount(0);
});

test("versions: save base → edit → save as scenario → compare → promote; the base is unchanged", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/versions");
  await page.getByLabel("Version name").fill("October cycle");
  await page.getByRole("button", { name: "Save as base version" }).click();
  await expect(page.locator(".version-chip")).toContainText("October cycle · base");
  const baseSha = await page.locator("tr", { hasText: "October cycle" }).locator("td[title]").getAttribute("title");

  // edit the working copy: modified; a base cannot be overwritten, so save as a scenario of it
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  await page.locator('input[id="on_hand"]').fill("20000");
  await page.locator('input[id="on_hand"]').press("Enter");
  await expect(page.locator(".version-chip")).toContainText("unsaved changes");
  await page.goto("/#/versions");
  await expect(page.getByRole("button", { name: /^Save to V/ })).toHaveCount(0);
  await page.getByLabel("Version name").fill("More heaters");
  await page.getByRole("button", { name: /Save as new scenario of V\d+/ }).click();
  await expect(page.locator(".version-chip")).toContainText("More heaters · scenario");
  await expect(page.locator(".version-chip")).not.toContainText("unsaved changes");

  // compare base (A) with the scenario (B)
  await page.getByRole("button", { name: "Compare V0001 as A" }).click();
  await page.getByRole("button", { name: "Compare V0002 as B" }).click();
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(page.getByText("Plan side by side (MRP)")).toBeVisible();
  await page.locator("tr.clickable", { hasText: "location products" }).click();
  await expect(page.getByText("on_hand: 14000 → 20000")).toBeVisible();

  // promote: a new base; the old one is superseded but byte-identical
  await page.getByRole("button", { name: "Promote V0002" }).click();
  await expect(page.locator("tr", { hasText: "V0003" }).getByText("active")).toBeVisible();
  await expect(page.locator("tr", { hasText: "October cycle" }).getByText("superseded")).toBeVisible();
  expect(await page.locator("tr", { hasText: "October cycle" }).locator("td[title]").getAttribute("title")).toBe(baseSha);
});

test("finance: cost the plan → books close → cost to serve by region → capacity NPV → edit option → stale", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/finance");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.locator(".banner", { hasText: "Books balance" })).toBeVisible();

  await page.getByRole("tab", { name: /Cost to serve & margin/ }).click();
  await page.getByRole("button", { name: "By region" }).click();
  await expect(page.locator("td b", { hasText: "North" })).toBeVisible();

  await page.getByRole("tab", { name: /Capacity investments/ }).click();
  await expect(page.locator("td b", { hasText: "Fourth winding machine" })).toBeVisible();
  await expect(page.getByText("capacity is not the constraint")).toBeVisible();
  await page.getByLabel("Discount rate").fill("9");
  await page.getByLabel("Discount rate").blur();
  await expect(freshness(page, "finance")).toHaveAttribute("data-fresh", "stale");
});

test("control tower: KPIs graded → drill into OTIF → worklist → assign & acknowledge → survives refresh", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/tower");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.locator(".kpi-card")).toHaveCount(13);
  await page.getByRole("button", { name: /^OTIF to requested date:/ }).click();
  await expect(page.locator(".section-band h2", { hasText: "OTIF to requested date" })).toBeVisible();
  await expect(page.locator("td", { hasText: "CUS-ECOM" }).first()).toBeVisible();

  await page.getByRole("tab", { name: /Exception worklist/ }).click();
  const owner = page.getByLabel(/^Owner of DEMAND_AT_RISK/).first();
  await owner.fill("Asha Kulkarni");
  await owner.press("Enter");
  await page.getByRole("button", { name: /^Ack DEMAND_AT_RISK|^Acknowledge DEMAND_AT_RISK/ }).first().click();
  await expect(page.locator(".tile", { hasText: "Acknowledged" }).locator(".value")).toHaveText("1");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.locator(".tile", { hasText: "Acknowledged" }).locator(".value")).toHaveText("1");
  await expect(page.locator('input[value="Asha Kulkarni"]')).toHaveCount(1);
});

test("phone: the menu opens the pages, each page answers first, nothing scrolls sideways", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openExample(page, "Kaveri Kitchenware");
  await expect(page.locator("#main-nav")).toBeHidden();
  await page.getByRole("button", { name: "☰ Menu" }).click();
  await expect(page.locator("#main-nav")).toBeVisible();
  await page.locator("#main-nav").getByRole("link", { name: "Orders", exact: true }).click();
  await expect(page.locator("#main-nav")).toBeHidden();                 // picking a page closes the menu
  await expect(page.locator(".stage-head .answer")).toContainText("customer orders can ship in full");
  for (const hash of ["#/", "#/plan", "#/promise", "#/finance", "#/tower", "#/data", "#/capacity", "#/schedule/orders", "#/schedule/methods", "#/buying", "#/buying/orders", "#/buying/suppliers"]) {
    await page.goto(`/${hash}`);
    await page.waitForTimeout(300);
    expect(await page.evaluate(() => document.documentElement.scrollWidth), hash).toBeLessThanOrEqual(390);
  }
});

test("upload: demand pasted from a spreadsheet, by name, with a preview of what is added and what can't be read", async ({ page }) => {
  await openExample(page, "Single-product bottler");
  await page.goto("/#/demand");
  await page.getByRole("button", { name: "Upload CSV / Excel" }).click();
  await page.getByText("…or paste from a spreadsheet").click();
  await page.getByLabel("Paste rows").fill("Place\tItem\tWeek of\tQty\nPLANT\tBTL-1L\t05/10/2026\t1,000\nNOWHERE\tBTL-1L\t05/10/2026\t5\n");
  await page.getByRole("button", { name: "Read the pasted rows" }).click();
  await expect(page.getByText("1 new")).toBeVisible();
  await expect(page.getByText(/there is no location “NOWHERE”/)).toBeVisible();
  await page.getByRole("button", { name: "Import 1 row" }).click();
  await expect(page.getByText(/1 row imported; 1 skipped/)).toBeVisible();
  await page.goto("/#/data/demand");
  await expect(page.locator("td", { hasText: /^2026-10-05$/ })).toHaveCount(2);
  await expect(page.locator("td", { hasText: /^1000$/ })).toHaveCount(1);
});

test("machines & shifts: named shifts and a shutdown change the hours the supply plan uses", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/machines/PUNE-L2");
  await expect(page.getByRole("heading", { name: /Assembly line 2/ })).toBeVisible();
  await page.getByLabel("Use a pattern").selectOption("two");
  await expect(page.getByLabel("Shift name")).toHaveCount(2);
  await expect(page.locator("svg[aria-label='Working hours in a sample week'] rect").first()).toBeVisible();
  // a week of maintenance: no hours that week, and the supply plan goes out of date
  await page.getByRole("button", { name: "+ Add a change" }).click();
  await page.getByLabel("To").first().fill("2026-10-03");   // the plant works Saturdays
  const weeks = page.getByRole("region", { name: "Hours week by week" }).or(page.locator("section.panel", { hasText: "Hours week by week" }));
  await expect(weeks.getByRole("row", { name: /28 Sep/ })).toContainText(/^Mon 28 Sep0/);
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "stale");
  await page.getByRole("button", { name: /Plan everything/ }).click();
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh", { timeout: 45_000 });
  // the plan's load sits beside the hours, so a week that needs more than it has stands out
  await expect(weeks.getByRole("columnheader", { name: "Plan needs" })).toBeVisible();
  await expect(weeks.getByRole("row", { name: /28 Sep/ })).toContainText(/^Mon 28 Sep0/);
});

test("products at places: MRP views, the structure explorer and the stock/requirements list", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.locator('.rail a[href="#/material"]').click();
  await expect(page.getByRole("heading", { name: "Products at places" })).toBeVisible();
  await page.locator('a[href="#/material/MG-500/PLT-PUNE"]').click();
  // stock and requirements: every receipt and requirement by date, with the stock after it
  await expect(page.getByRole("heading", { name: /Receipts and requirements/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: "On hand today" })).toBeVisible();
  // MRP 1: give it an owner, then filter the index by that owner
  await page.getByRole("tab", { name: /MRP 1/ }).click();
  await page.getByLabel(/MRP controller/).fill("Asha");
  await page.getByRole("tab", { name: /MRP 4/ }).click();
  await expect(page.getByRole("heading", { name: /What one Mixer grinder 500 W is made from/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: /Enamelled copper wire/ })).toBeVisible();   // second level, through the motor
  await page.goto("/#/material");
  await page.getByLabel("Planned by").selectOption("Asha");
  await expect(page.locator("tbody tr")).toHaveCount(1);
});

test("capacity levelling: daily overloads the weeks hide → preview → plan within capacity → keep the dates", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/capacity");
  await expect(page.locator(".stage-head .answer")).toContainText(/asked for more than they have on \d+ days/);
  await page.getByRole("button", { name: "Show what levelling moves" }).click();
  await expect(page.getByText(/Levelling moves \d+ orders/)).toBeVisible({ timeout: 30_000 });
  // every machine goes from overloaded days to none
  await expect(page.getByRole("row", { name: /Assembly line 1/ })).toContainText(/→ 0/);
  // a day's orders, from the chart
  await page.getByRole("tab", { name: /Assembly line 1/ }).click();
  const chart = page.locator("svg.chart").first();
  const box = (await chart.boundingBox())!;
  await chart.hover({ position: { x: box.width * 0.5, y: box.height * 0.6 } });
  await chart.click({ position: { x: box.width * 0.5, y: box.height * 0.6 } });
  await expect(page.getByRole("heading", { name: /Orders on Assembly line 1/ })).toBeVisible();
  // switch it on: the plan recalculates within capacity and no day is over
  await page.getByRole("button", { name: "Plan within capacity" }).click();
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh", { timeout: 45_000 });
  await expect(page.locator(".stage-head .answer")).toContainText("because the plan keeps within capacity");
  await page.getByRole("button", { name: "Keep these dates" }).click();
  await page.getByRole("button", { name: "Keep the dates" }).click();
  await expect(page.getByText(/kept at their levelled dates as production orders/)).toBeVisible({ timeout: 45_000 });
});

test("shop floor: steps wait for parts, and the schedule's dates go back into the plan", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/schedule/orders");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Waiting for parts")).toBeVisible({ timeout: 45_000 });
  const waited = page.locator("tr.clickable", { hasText: "waited" }).first();
  await waited.click();
  await expect(page.getByText(/Waited .* for parts/)).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Comes from" })).toBeVisible();
  await page.getByRole("button", { name: "Use these dates in the plan" }).click();
  await expect(page.getByRole("alertdialog", { name: "Use the schedule's dates" })).toBeVisible();
  await page.getByRole("button", { name: "Use the dates" }).click();
  await expect(page.getByText(/became production orders with the schedule's dates/)).toBeVisible({ timeout: 45_000 });
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "fresh", { timeout: 45_000 });
  // the plan now shows the late ones as late, not as new orders
  await page.goto("/#/plan");
  await expect(page.getByText(/production orders? the shop floor schedule finishes late/)).toBeVisible();
  // undo puts the planned orders back
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "stale");
});
