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
/** Accept an invitation by its link, signed in as the invited address (CV-C01), then come back to the account page. */
const acceptInvite = async (p: Page, link: string) => {
  await expect(p.getByRole("button", { name: "Sign out" })).toBeVisible();
  await p.goto(link.replace(/^https?:\/\/[^/]+/, ""));
  await p.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(p.getByText(/You joined /)).toBeVisible();
  await p.goto("/#/account");
  await p.reload();
};

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
  const cell = page.getByLabel(/^Electric kettle 1\.5 L at E-commerce marketplaces,/).first();
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
  // the release was made on Demand: Undo acts there, never from another screen (QA: a global stack resurrected deletions)
  const undo = page.getByRole("button", { name: "Undo" });
  await expect(undo).toBeDisabled();
  await expect(undo).toHaveAttribute("title", /made on Demand/);
  await page.goto("/#/demand/consensus");
  await undo.click();
  await page.goto("/#/data/demand");
  await page.getByLabel("Search").fill("KT-15");
  await expect(released).toHaveCount(0);
});

test("typed inputs: a percent typed as a fraction is rejected with the field named", async ({ page }) => {
  await openExample(page, "Single-product bottler");
  await page.goto("/#/settings");
  const wacc = page.locator('input[id="wacc"]');
  await expect(wacc).toHaveValue("12"); // shown as percent, stored as 0.12
  // its limits are said in the unit it is typed in (QA: "0 … 1" beside a WACC of 12 %)
  await expect(wacc).toHaveAttribute("title", "Allowed: 0 … 100 %");
  // a value outside them is not saved (QA: out-of-range values were accepted): the field goes back and says why
  await wacc.fill("1200");
  await wacc.press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "1200 is outside the range. Allowed: 0 … 100 %." })).toBeVisible();
  await expect(wacc).toHaveValue("12");
  await expect(page.getByText("Invalid values", { exact: true })).toHaveCount(0);
  await wacc.fill("13");
  await wacc.press("Enter");
  await expect(page.locator(".input-wrap .err")).toHaveCount(0);
  await expect(wacc).toHaveValue("13");
});

test("blank network: the checklist and guided setup take a planner from nothing to a plan", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Start with an empty company" }).click();
  // the company comes first: its name, currency, working week and how much an order covers (Q12, Q7)
  await page.getByLabel("Company name").fill("Oil Works");
  await expect(page.getByLabel("Each order covers")).toHaveValue("week");
  await page.getByRole("group", { name: "Working days" }).getByLabel("Sat").check();
  await page.getByRole("button", { name: "Create the company" }).click();
  await expect(page.getByText(/Oil Works: INR, planning from .*, each order covers a week's need\./)).toBeVisible();
  await expect(page.locator(".company")).toHaveText("Oil Works");
  await page.goto("/#/home");
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
  // the step runs in batches of 50, 2 hours each however full (Q8)
  await make.getByLabel("How the step runs").selectOption("batch");
  await make.getByLabel("Batch size").fill("50");
  await make.getByLabel("Hours per batch").fill("2");
  await make.getByRole("button", { name: "Save" }).click();
  await page.getByRole("link", { name: "Set it up" }).click();
  await page.getByRole("button", { name: "Buy it" }).click();
  // the supplier invoices in dollars: the price stays in USD with the rate kept once (Q16)
  const buy = page.locator(".wz-card.attn .wz-form").first();
  await buy.locator("label.qf", { hasText: "Price per unit" }).locator("input").fill("0.5");
  await buy.getByLabel("Price currency").fill("USD");
  await buy.getByLabel("INR per USD").fill("84");
  await buy.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText(/Bought from Supplier A at 0.5 USD/)).toBeVisible();

  // the checklist now asks only for demand; a sales sheet with the months across the top becomes monthly forecasts (Q11)
  await page.goto("/#/readiness");
  await expect(page.getByText("Nothing to plan yet: no product has any demand.")).toBeVisible();
  await page.goto("/#/demand");
  await page.getByRole("button", { name: "Upload CSV / Excel" }).click();
  await page.getByText("…or paste from a spreadsheet").click();
  const month = (n: number) => { const d = new Date(); d.setDate(1); d.setMonth(d.getMonth() + n); return d.toLocaleString("en-GB", { month: "short", year: "numeric" }); };
  await page.getByLabel("Paste rows").fill(`Product\tCustomer\t${month(1)}\t${month(2)}\nOil filter\tPune plant\t1,210\t990\n`);
  await page.getByRole("button", { name: "Read the pasted rows" }).click();
  await expect(page.getByText("The file has 2 periods across the top")).toBeVisible();
  await expect(page.getByText("2 new")).toBeVisible();
  await page.getByRole("button", { name: "Import 2 rows" }).click();
  await page.goto("/#/readiness");
  await expect(page.getByText("Ready to plan")).toBeVisible();
  await page.goto("/#/network");
  await expect(page.locator(".net .node")).toHaveCount(3);

  // each run covers a week's need, in whole batches of 50
  await page.goto("/#/plan/orders");
  await page.getByRole("button", { name: /Recalculate|Calculate/ }).first().click();
  await expect(page.locator("tbody tr").filter({ hasText: /^MO-/ }).first()).toBeVisible();
  const qtys = await page.locator("tbody tr").filter({ hasText: /^MO-/ }).evaluateAll((rows) =>
    rows.map((r) => Number((r.querySelectorAll("td.num")[0]?.textContent ?? "").replace(/[^\d.]/g, ""))));
  expect(qtys.length).toBeGreaterThan(1);
  expect(qtys.length).toBeLessThan(15);
  for (const q of qtys) expect(q % 50).toBe(0);
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
  await page.getByLabel("Select Rotary switch + PCB at Pune plant (Chakan)").check();
  await page.getByRole("button", { name: /Review 1 change/ }).click();
  await page.getByRole("button", { name: "Use these buffers in the plan" }).click();
  await expect(freshness(page, "inventory")).toHaveAttribute("data-fresh", "stale");
  await page.getByRole("button", { name: "Recalculate now" }).click();
  await expect(freshness(page, "inventory")).toHaveAttribute("data-fresh", "fresh");
  const row = page.locator("tr", { has: page.getByLabel("Select Rotary switch + PCB at Pune plant (Chakan)") });
  await expect(row.locator("td").nth(10)).toContainText("fixed");

  await page.goto("/#/inventory/ddmrp");
  await page.getByLabel("Show every stocking stage").check();
  await page.getByLabel("Position a buffer of Mixer grinder 500 W at Delhi NCR DC").check();
  await page.getByRole("button", { name: "Recalculate now" }).click();
  await page.getByLabel("Show every stocking stage").uncheck();
  await expect(page.getByLabel("Position a buffer of Mixer grinder 500 W at Delhi NCR DC")).toBeChecked();
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
  await page.goto("/#/sop");                                              // undone where it was made
  await page.getByRole("button", { name: "Undo" }).click();
  await page.goto("/#/data/demand");
  await page.getByLabel("Search").fill("SOP-");
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
  await expect(page.getByText("MO-00024 · Mixer grinder 500 W")).toBeVisible();
  await page.getByRole("button", { name: "later ▶" }).first().click();
  await expect(page.getByText("Your sequence")).toBeVisible();
  await page.getByRole("button", { name: "Undo my changes to the order" }).click();
  await expect(page.getByText("Your sequence")).toHaveCount(0);

  await page.goto("/#/schedule/orders");
  await expect(page.locator("td", { hasText: "MO-100455" })).toBeVisible();

  // the setup matrix edits the dataset: the schedule goes stale
  await page.goto("/#/schedule/setups");
  await page.getByRole("button", { name: "Hi-pot & run test benches" }).click();
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
  await expect(page.getByText("Your sequence", { exact: true })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/step \d+ moved.*Late orders \d+ → \d+/)).toBeVisible();
  await page.getByRole("button", { name: "Undo my changes to the order" }).click();
  await expect(page.getByText("Your sequence", { exact: true })).toHaveCount(0, { timeout: 60_000 });
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

test("customer orders: check a new order → take it → change it → deliver part → cancel the rest", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/promise/simulate");
  await page.getByLabel("Quantity").fill("40");
  await page.getByLabel("Customer's order number").fill("PO-7781");
  await expect(page.getByRole("button", { name: "Take this order" })).toBeDisabled();       // check it first
  await page.getByRole("button", { name: "Check availability" }).click();
  await page.getByRole("button", { name: "Take this order" }).click();
  const saved = page.locator(".banner.info", { hasText: "Saved" });
  await expect(saved).toContainText(/SO-88222 taken: 40 /);   // the company's own numbering, continued
  await expect(page).toHaveURL(/#\/promise\/orders\/SO-88222$/);
  await expect(page.locator("tr", { hasText: "SO-88222" }).first()).toContainText("PO-7781");

  await page.getByRole("button", { name: "Change", exact: true }).click();
  await page.getByLabel("Ordered quantity").fill("50");
  await page.getByLabel("Price a unit").fill("999");
  await page.getByRole("button", { name: "Save and promise again" }).click();
  await expect(saved).toContainText("SO-88222 changed (quantity 40 → 50, price 999)");
  await expect(page.locator(".tile", { hasText: "Order value" })).toContainText("999");

  await page.getByRole("button", { name: "Deliver", exact: true }).click();
  await page.getByLabel("Quantity to deliver").fill("20");
  await page.getByRole("button", { name: "Post the delivery" }).click();
  await expect(saved).toContainText("SO-88222: 20 delivered");
  await expect(saved).toContainText("30 still open");

  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("button", { name: "Cancel the 30 still open" }).click();
  await expect(saved).toContainText("SO-88222 cancelled: 20 delivered, 30 no longer wanted");
  await page.goto("/#/data/closed_orders");
  await expect(page.locator("tr", { hasText: "SO-88222" })).toBeVisible();
  // Undo acts on the screen the change was made on (the cancel was made on Orders), never from another one
  const undo = page.getByRole("button", { name: "Undo" }).first();
  await expect(undo).toBeDisabled();
  await expect(undo).toHaveAttribute("title", /open it to undo it/);
  await page.goto("/#/promise/orders");
  await undo.click();
  await page.goto("/#/data/demand");
  await expect(page.locator("tr", { hasText: "SO-88222" })).toBeVisible();                          // undo brings it back
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
  await page.getByRole("button", { name: "Deliver SO-88190" }).click();
  await expect(page.locator(".banner.info", { hasText: "Posted" })).toContainText("SO-88190");

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
  await expect(page.locator("td b", { hasText: /^PRD-\d{5}$/ }).first()).toBeVisible();
  await expect(page.getByText(/^was MO-\d{5}$/).first()).toBeVisible();     // the planned number it came from (Q22)
});

test("posting: count stock → firm → ship and receive a transfer → confirm production with its parts → a late posting is offered", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  const posted = page.locator(".banner.info", { hasText: "Posted" });

  // count: the difference is posted, the plan starts from the count
  await page.goto("/#/execution/count");
  const cell = page.locator('input[aria-label^="Counted"]').first();
  const was = Number((await cell.getAttribute("placeholder"))!.replace(/,/g, ""));
  await cell.fill(String(was + 7));
  await page.getByRole("button", { name: "Save 1 count" }).click();
  await expect(page.locator(".banner", { hasText: "Saved" })).toContainText(/1 count as of/);

  // firm one production order and one transfer
  await page.goto("/#/execution/orders");
  await page.getByRole("button", { name: /^(Recalculate the supply plan|Calculate the supply plan)$/ }).click();
  await page.getByRole("button", { name: "Select none" }).click();
  await page.locator("tr.clickable", { hasText: "production order" }).first().locator("input").check();
  await page.locator("tr.clickable", { hasText: "stock transfer" }).first().locator("input").check();
  await page.getByRole("button", { name: "Make 2 orders firm" }).click();
  await expect(page.getByText(/2 planned orders firmed/)).toBeVisible();

  // the transfer ships (in transit), then arrives
  const sto = (await page.locator("td b", { hasText: /^STO-\d{5}$/ }).first().innerText()).trim();
  await page.getByRole("button", { name: `Ship ${sto}`, exact: true }).click();
  await expect(posted).toContainText("now in transit");
  await page.getByRole("button", { name: `Receive ${sto}`, exact: true }).click();
  await expect(posted).toContainText("(complete)");
  await expect(page.getByRole("button", { name: `Ship ${sto}`, exact: true })).toBeDisabled();

  // the production order is confirmed a day before the start: its parts are issued, and it is a late posting
  const start = await page.locator("#post-date").inputValue();
  const d = new Date(start + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() - 1);
  await page.locator("#post-date").fill(d.toISOString().slice(0, 10));
  const prd = (await page.locator("td b", { hasText: /^PRD-\d{5}$/ }).first().innerText()).trim();
  await page.getByRole("button", { name: `Post part of ${prd}` }).click();
  await expect(page.getByText("Parts issued with it")).toBeVisible();
  await page.locator("tr.sub").getByRole("button", { name: /^Confirm/ }).click();
  await expect(posted).toContainText(/parts? issued in proportion/);
  await page.goto("/#/execution/journal");
  await expect(page.locator("td", { hasText: prd }).first()).toBeVisible();
  await expect(page.locator("tr", { hasText: prd }).filter({ hasText: "issue" }).first()).toBeVisible();

  await page.goto("/#/execution/stock");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await expect(page.getByText("Not counted yet")).toBeVisible();
  await page.getByRole("button", { name: "Count them now" }).click();
  await expect(page.getByText("Not counted yet")).toHaveCount(0);
});

test("stock you can trace: a short receipt names the order it leaves short → shorten it → batches in stock → block → reverse → physical inventory", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  const posted = page.locator(".banner.info", { hasText: "Posted" });

  // no heating elements left at the plant, so the kettles made there depend on the next delivery
  await page.goto("/#/execution/count");
  await page.getByLabel("Counted Concealed heating element at Pune plant (Chakan)").fill("0");
  await page.getByRole("button", { name: "Save 1 count" }).click();
  await expect(page.locator(".banner", { hasText: "Saved" })).toContainText("1 count difference");

  // firm the zone, then the heater delivery comes in short, in the supplier's batch, and closes the line
  await page.goto("/#/execution/orders");
  await page.getByRole("button", { name: /^(Recalculate the supply plan|Calculate the supply plan)$/ }).click();
  await page.getByRole("button", { name: /Make \d+ orders? firm/ }).click();
  await expect(page.getByText(/planned orders? firmed/)).toBeVisible();
  const line = page.locator("tr", { hasText: "Concealed heating element" }).filter({ hasText: "purchase" }).first();
  const po = (await line.locator("td").first().innerText()).trim().split(/\s+/)[0];
  await page.getByRole("button", { name: `Post part of ${po}` }).click();
  await page.getByLabel(`Quantity for ${po}`).fill("10");
  await page.getByText("Last delivery: close the order even if short").click();
  await page.getByLabel(/^Batch of/).fill("HT-1");
  await page.getByRole("button", { name: /^Receive [0-9,.]+$/ }).click();
  await expect(posted).toContainText("in batch HT-1");
  await expect(posted).toContainText("closed 9,990 short");
  const short = page.locator(".banner.warning", { hasText: "Can no longer run in full" });
  await expect(short).toContainText("Concealed heating element");
  await short.getByRole("button", { name: /^Shorten to \d+$/ }).first().click();
  await expect(short.getByText("shortened")).toBeVisible();
  await expect(posted).toContainText(/shortened from 1,450 to \d+/);

  // the batch is in stock now, this week's postings included; block it
  await page.goto("/#/execution/stock");
  await page.getByLabel("Find stock").fill("HT-1");
  await page.getByRole("button", { name: "Batches and stock of RM-HEATER at PLT-PUNE" }).click();
  const lot = page.locator("tr.sub tr", { hasText: "HT-1" }).filter({ hasText: "free to use" });
  await expect(lot).toContainText("10");
  await lot.getByRole("button", { name: "Block" }).click();
  await expect(posted).toContainText("blocked");
  await expect(page.locator("tr.sub tr", { hasText: "HT-1" }).filter({ hasText: "blocked" })).toBeVisible();

  // the receipt is taken back from the journal: its material document, and the order is open again
  await page.goto("/#/execution/journal");
  await page.getByLabel("Find movements").fill("HT-1");
  const receipt = page.locator("tr", { hasText: "HT-1" }).filter({ hasText: "receipt" }).first();
  await receipt.getByRole("button", { name: /^Reverse / }).click();
  await expect(page.locator(".banner", { hasText: "Reversed" })).toContainText(`${po} is open again`);
  await expect(page.locator("tr", { hasText: "HT-1" }).filter({ hasText: "reversed" }).first()).toBeVisible();

  // a physical inventory of the plant: the book is frozen, postings for it wait, the count is cancelled
  await page.goto("/#/execution/count");
  await page.selectOption('select[aria-label="Place to count"]', { label: "Pune plant (Chakan)" });
  await page.getByRole("button", { name: /^Start counting \d+ products$/ }).click();
  await expect(page.locator(".banner", { hasText: "Done" })).toContainText("book stock frozen");
  await expect(page.getByRole("button", { name: "Post differences" })).toBeDisabled();
  await page.getByRole("button", { name: "Cancel the count" }).click();
  await expect(page.locator(".banner", { hasText: "Done" })).toContainText("cancelled");

  // the company's rule for stock below zero
  await page.goto("/#/execution/stock");
  await page.getByText("Stock rules").click();
  await expect(page.locator("select#negative_stock option", { hasText: "Refuse the posting" })).toHaveCount(1);
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
  await expect(page.locator(".banner.ok")).toContainText("sent to Rajkot jar works");
  // the order as a document, with the supplier's, the plant's and the company's addresses (N69)
  await expect(page.getByText(/^No address yet/)).toHaveCount(0);
  const [doc] = await Promise.all([page.context().waitForEvent("page"), page.getByRole("button", { name: "Print or PDF" }).click()]);
  await expect(doc.locator("body")).toContainText("Shed 32, Aji GIDC");
  await expect(doc.locator("body")).toContainText("Plot 21, MIDC Chakan Phase II");
  await expect(doc.locator("body")).toContainText("Invoice to");
  await doc.close();

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
  await page.goto("/#/buying");                                           // undone where it was made
  await page.getByRole("button", { name: "Undo" }).first().click();
  await page.goto("/#/readiness");
  await expect(page.getByText(/only purchasing sources are blocked/)).toHaveCount(0);
});

test("versions: save base → edit → save as scenario → compare → promote; the base is unchanged", async ({ page }) => {
  const workingId = () => page.locator("section.panel").filter({ has: page.getByRole("heading", { name: "Working copy", exact: true }) }).locator("b").first().textContent();
  const versionRow = (id: string) => page.locator("tbody tr").filter({ has: page.getByRole("button", { name: `Open ${id}`, exact: true }) });
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/versions");
  await page.getByLabel("Version name").fill("October cycle");
  await page.getByRole("button", { name: "Save as base version" }).click();
  await expect(page.locator(".version-chip")).toContainText("October cycle · base");
  const baseId = (await workingId())!;
  const baseSha = await versionRow(baseId).locator("td[title]").getAttribute("title");

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
  const scenarioId = (await workingId())!;

  // compare base (A) with the scenario (B)
  await page.getByRole("button", { name: `Compare ${baseId} as A` }).click();
  await page.getByRole("button", { name: `Compare ${scenarioId} as B` }).click();
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(page.getByText("Plan side by side (MRP)")).toBeVisible();
  await page.locator("tr.clickable", { hasText: "location products" }).click();
  await expect(page.getByText("on_hand: 14000 → 20000")).toBeVisible();

  // promote: a new base; the old one is superseded but byte-identical
  await page.getByRole("button", { name: `Promote ${scenarioId}` }).click();
  await expect(page.locator(".version-chip")).toContainText("· base");
  await expect(versionRow((await workingId())!).getByText("active", { exact: true })).toBeVisible();
  await expect(versionRow(baseId).getByText("superseded", { exact: true })).toBeVisible();
  expect(await versionRow(baseId).locator("td[title]").getAttribute("title")).toBe(baseSha);
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
  await expect(page.locator("td", { hasText: "E-commerce marketplaces" }).first()).toBeVisible();

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
  for (const hash of ["#/", "#/plan", "#/promise", "#/finance", "#/tower", "#/data", "#/capacity", "#/schedule/orders", "#/schedule/methods", "#/buying", "#/buying/orders", "#/buying/suppliers", "#/execution/count", "#/execution/orders"]) {
    await page.goto(`/${hash}`);
    await expect(page.locator("main :is(h1, h2)").first()).toBeVisible();   // the page drawn, not a wait on time
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
  // undo puts the planned orders back, from the shop floor where the dates were taken over
  await expect(page.getByRole("button", { name: "Undo" })).toBeDisabled();
  await page.goto("/#/schedule/orders");
  await page.getByRole("button", { name: "Undo" }).click();
  await page.goto("/#/plan");
  await expect(freshness(page, "plan")).toHaveAttribute("data-fresh", "stale");
});

test("company on the server: sign up → keep it there → saves itself → a colleague saves first → merged by itself → both change one order → merge both → history → put back; a viewer changes nothing", async ({ page, browser }) => {
  page.on("dialog", (d) => d.accept());
  await openExample(page, "Kaveri Kitchenware");
  const chip = page.locator(".save-chip .save-long");
  await expect(chip).toHaveText("In this browser only");

  // sign up and keep the company on the server
  await chip.click();
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill("asha@kaveri.in");
  await page.getByLabel("Your name").fill("Asha Rao");
  await page.getByLabel(/^Password/).fill("kaveri-2026-pumps");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(chip).toHaveText("Saved");
  // nobody joins unasked (CV-C01): adding someone makes an invitation whose link they accept
  const invites: Record<string, string> = {};
  await page.getByLabel("Colleague's e-mail").fill("ravi@kaveri.in");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.locator("tr", { hasText: "ravi@kaveri.in" })).toContainText("invited");
  invites["ravi@kaveri.in"] = await page.getByLabel("Invitation link").inputValue();
  await page.getByLabel("Colleague's e-mail").fill("meera@kaveri.in");
  await page.getByLabel("Their role").selectOption("viewer");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.locator("tr", { hasText: "meera@kaveri.in" })).toContainText("viewer");
  invites["meera@kaveri.in"] = await page.getByLabel("Invitation link").inputValue();

  const take = async (p: Page, q: number, ref: string) => {
    await p.goto("/#/promise/simulate");
    await p.getByLabel("Quantity").fill(String(q));
    await p.getByLabel("Customer's order number").fill(ref);
    await p.getByRole("button", { name: "Check availability" }).click();
    await p.getByRole("button", { name: "Take this order" }).click();
  };
  const colleague = async (email: string, name: string) => {
    const p = await (await browser.newContext()).newPage();
    await p.goto("/#/account");
    await p.getByRole("tab", { name: "Make an account" }).click();
    await p.getByLabel("E-mail").fill(email);
    await p.getByLabel("Your name").fill(name);
    await p.getByLabel(/^Password/).fill("colleague-pw-0001");
    await p.getByRole("button", { name: "Make the account" }).click();
    await acceptInvite(p, invites[email]);
    await p.getByRole("button", { name: /Open Kaveri Kitchenware/ }).click();
    await expect(p.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
    return p;
  };

  // a change saves itself
  await take(page, 10, "ASHA-1");
  await expect(page.locator(".banner.info", { hasText: "Saved" })).toContainText("SO-88222 taken");
  await expect(chip).toHaveText(/^Saved \d\d:\d\d$/);

  // Ravi, a planner, opens it and takes an order; Asha takes one too before seeing his
  const ravi = await colleague("ravi@kaveri.in", "Ravi Menon");
  await take(ravi, 20, "RAVI-1");
  await expect(ravi.locator(".save-chip .save-long")).toHaveText(/^Saved \d\d:\d\d$/);
  // they changed different records: Asha's refused save merges by itself and says so
  await take(page, 30, "ASHA-2");
  await expect(page.locator(".save-banner")).toContainText("Ravi Menon saved while you were working; both sets of changes are kept");
  await expect(page.locator(".save-banner")).toContainText("SO-88223 → SO-88224");
  await expect(chip).toHaveText(/^Saved \d\d:\d\d$/);
  await page.locator(".save-banner").getByRole("button", { name: "OK" }).click();
  await ravi.reload();
  await ravi.goto("/#/data/demand");
  await expect(ravi.locator("tr", { hasText: "SO-88224" })).toHaveText(/sales_order30$/);   // both orders are kept
  await expect(ravi.locator("tr", { hasText: "SO-88223" })).toHaveText(/sales_order20$/);

  // both change the same order: that is not merged silently, Asha is asked
  const change = async (p: Page, q: number) => {
    await p.goto("/#/promise/orders/SO-88222");
    await p.getByRole("button", { name: "Change", exact: true }).click();
    await p.getByLabel("Ordered quantity").fill(String(q));
    await p.getByRole("button", { name: "Save and promise again" }).click();
    await expect(p.locator(".banner.info", { hasText: "Saved" })).toContainText(`SO-88222 changed (quantity 10 → ${q}`);
  };
  await change(ravi, 12);
  await expect(ravi.locator(".save-chip .save-long")).toHaveText(/^Saved \d\d:\d\d$/);
  await change(page, 15);
  await expect(chip).toHaveText("Not saved · saved by someone else");
  await expect(page.locator(".save-banner")).toContainText("Ravi Menon saved Kaveri");
  await page.getByRole("button", { name: "Merge both" }).click();
  // the one order both changed (with its promise), side by side: she chooses whose to keep (his, here)
  const chooser = page.locator(".clash-chooser");
  await expect(chooser).toContainText("You and Ravi Menon both changed one record");
  await expect(chooser.locator("legend")).toHaveText("Order SO-88222 and its promise");
  await expect(chooser.locator("tr", { hasText: "orders and forecasts: qty" })).toContainText(/10\s*15\s*12/);
  await chooser.getByRole("button", { name: "Merge, keeping Ravi Menon's" }).click();
  await expect(page.locator(".save-banner")).toContainText("Merged with Ravi Menon");
  await expect(page.locator(".save-banner")).toContainText("Changed on both sides, their version kept");
  await expect(chip).toHaveText(/^Saved/);
  await page.goto("/#/data/demand");
  await expect(page.locator("tr", { hasText: "SO-88222" })).toHaveText(/sales_order12$/);    // his change stands

  // the history says who changed what; put the company back to before the merge
  await page.goto("/#/history");
  await expect(page.locator("ol.history > li").first()).toContainText("Ravi Menon");     // the clash kept his: nothing new of hers
  await expect(page.locator("ol.history > li", { hasText: "Asha Rao" }).first()).toContainText("merged with Ravi Menon's save");
  const ravis = page.locator("ol.history > li", { hasText: "Ravi Menon" }).filter({ hasText: "saved" }).last();   // his first save
  await ravis.getByRole("button", { name: "Which records" }).click();
  await expect(ravis).toContainText("+ SO-88223");
  await ravis.getByRole("button", { name: "Put back to this" }).click();
  await expect(page.locator(".banner.ok:not(.save-banner)")).toContainText("Put back to revision");
  await expect(page.locator("ol.history > li").first()).toContainText("put back");

  // Meera, a viewer, can look but changes nothing
  const meera = await colleague("meera@kaveri.in", "Meera");
  await expect(meera.locator(".save-chip .save-long")).toHaveText("View only");
  // the buttons that change data are shown disabled (N62); anything else that tries is refused with the reason
  await meera.goto("/#/promise/simulate");
  await meera.getByLabel("Quantity").fill("5");
  await meera.getByRole("button", { name: "Check availability" }).click();
  await expect(meera.getByRole("button", { name: "Take this order" })).toBeDisabled();
  await meera.goto("/#/data/products");
  await expect(meera.getByRole("button", { name: /New product/ })).toBeDisabled();
  // nor type into a grid (N70); a page whose result was never calculated here calculates on opening (N71)
  await meera.goto("/#/execution/count");
  await expect(meera.getByLabel(/^Counted .* at /).first()).toBeDisabled();
  await meera.reload();
  await meera.goto("/#/buying");
  await expect(meera.locator(".stage-head .answer")).toContainText("should be ordered in the next 7 days");
});

test("rights and four eyes: a planner limited to a place is refused elsewhere; master data waits for a second person, who approves it; every field is on record", async ({ page, browser }) => {
  page.on("dialog", (d) => d.accept());
  await openExample(page, "Kaveri Kitchenware");
  await page.locator(".save-chip .save-long").click();
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill("owner@kaveri.in");
  await page.getByLabel("Your name").fill("Nisha Owner");
  await page.getByLabel(/^Password/).fill("kaveri-2026-pumps");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await page.getByLabel("Colleague's e-mail").fill("plan@kaveri.in");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const invitation = await page.getByLabel("Invitation link").inputValue();
  const p = await (await browser.newContext()).newPage();
  p.on("dialog", (d) => d.accept());
  await p.goto("/#/account");
  await p.getByRole("tab", { name: "Make an account" }).click();
  await p.getByLabel("E-mail").fill("plan@kaveri.in");
  await p.getByLabel("Your name").fill("Om Planner");
  await p.getByLabel(/^Password/).fill("colleague-pw-0001");
  await p.getByRole("button", { name: "Make the account" }).click();
  await acceptInvite(p, invitation);
  await p.getByRole("button", { name: /Open Kaveri Kitchenware/ }).click();

  // limited to the Delhi warehouse, he may not change the company's settings
  await page.reload();
  await page.locator("tr", { hasText: "plan@kaveri.in" }).getByRole("button", { name: "limit" }).click();
  await page.getByLabel("Places plan@kaveri.in may change").fill("DC-DELHI");
  await page.getByRole("button", { name: "Save limits" }).click();
  await expect(page.locator("tr", { hasText: "plan@kaveri.in" })).toContainText("Changes only Delhi");
  const address = async (text: string) => {
    await p.goto("/#/setup/company");
    await p.getByLabel("Company address").fill(text);
    await p.getByRole("button", { name: "Save", exact: true }).click();
  };
  await address("Plot 1, Chakan");
  await expect(p.locator(".save-banner")).toContainText("your rights cover the places DC-DELHI; this change also touches company settings");
  await p.getByRole("button", { name: "Undo the last change" }).click();
  await expect(p.locator(".save-chip .save-long")).toHaveText(/^Saved/);

  // no limit, but master data needs a second person: his change waits, the owner approves it
  await page.locator("tr", { hasText: "plan@kaveri.in" }).getByRole("button", { name: "limit" }).click();
  await page.getByLabel("Places plan@kaveri.in may change").fill("");
  await page.getByRole("button", { name: "Save limits" }).click();
  await page.getByLabel(/Master data changes need a second person/).check();
  await address("Plot 2, Chakan");
  await expect(p.locator(".save-banner")).toContainText("Your master data change (company settings changed) waits for a second person's approval");
  await page.goto("/#/history");
  const waiting = page.locator(".panel", { hasText: "Master data changes wait here" });
  await expect(waiting).toContainText("Om Planner");
  await expect(waiting.locator("tr", { hasText: "company address" })).toContainText("Plot 2, Chakan");
  await waiting.getByRole("button", { name: "Approve" }).click();
  await expect(page.locator(".banner.ok")).toContainText("Om Planner's change #1 approved and saved");
  await page.getByLabel("Record to find changes of").fill("");
  await page.getByRole("button", { name: "Find" }).click();
  await expect(page.locator(".panel", { hasText: "Changes to a record" }).locator("tbody tr").first()).toContainText("Plot 2, Chakan");
});

test("opening another company while one is planning: the first one's results are dropped and the new one is planned", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await openExample(page, "Kaveri Kitchenware");
  await page.locator(".save-chip .save-long").click();
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill("switch@kaveri.in");
  await page.getByLabel("Your name").fill("Sam Switch");
  await page.getByLabel(/^Password/).fill("kaveri-2026-pumps");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText("Saved");
  // a second company, the bottler, made on the server by the same person
  // roadmap D: the session cookie signs page.request in; a change carries the double-submit token
  const csrf = (await page.context().cookies()).find((c) => c.name === "scp_csrf")?.value ?? "";
  const bottler = await (await page.request.get("/api/examples/single_product_plant")).json();
  expect((await page.request.post("/api/companies", { headers: { "X-CSRF-Token": csrf },
    data: { dataset: bottler, note: "second company" } })).ok()).toBe(true);
  await page.goto("/#/account");
  await page.reload();

  // Kaveri's forecast takes long; the bottler is opened while Kaveri is still being planned
  let slow = true;
  await page.route("**/api/forecast", async (r) => {
    if (slow) await new Promise((ok) => setTimeout(ok, 4000));
    await r.continue();
  });
  const asked = page.waitForRequest("**/api/forecast");
  await page.getByRole("button", { name: /^Open Kaveri Kitchenware/ }).click();
  await asked;
  await expect(page).toHaveURL(/#\/home/);
  await page.goto("/#/account");
  await page.getByRole("button", { name: /^Open Single-product bottler/ }).click();
  slow = false;
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  // every result is the bottler's: Kaveri's forecast, which came back after the bottler was open, is not taken
  await page.goto("/#/demand");
  await expect(page.getByRole("tab", { name: "Demand plan" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Series workbench/ })).toHaveCount(0);   // the bottler has no sales history
  for (const at of ["#/demand", "#/plan/orders", "#/buying"]) {
    await page.goto("/" + at);
    await expect(page.locator("main")).toContainText(/Mineral water|PET preform|Cap \+ label/);
    await expect(page.locator("main")).not.toContainText(/Mixer grinder|Electric kettle|Enamelled copper|MG-500|MG-750|KT-15/);
  }
});

test("a company on the server is planned from the server's copy: calls name the save, a change comes back as what changed, pegging is asked for", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  await openExample(page, "Kaveri Kitchenware");
  await page.locator(".save-chip .save-long").click();
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill("ref@kaveri.in");
  await page.getByLabel("Your name").fill("Rhea Ref");
  await page.getByLabel(/^Password/).fill("kaveri-2026-pumps");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText("Saved");

  // every planning call names the save instead of carrying the company
  const sent: string[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/(validate|network|forecast|plan|promise|inventory|sop|schedule|purchasing|actuals|finance|tower)(\?|$)/.test(r.url())) sent.push(r.postData() ?? "");
  });
  await page.goto("/#/home");
  await page.getByRole("button", { name: /^Plan everything/ }).first().click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 60_000 });
  expect(sent.length).toBeGreaterThanOrEqual(10);
  for (const b of sent) {
    expect(b).toContain('"$ref"');
    expect(b.length).toBeLessThan(2_000);
  }

  // the plan comes without its pegging: an order's is asked for when it is opened
  await page.goto("/#/plan/orders");
  await page.locator("table.t tbody tr").first().click();
  await expect(page.locator(".peg-tree")).toContainText("Serves");

  // a change the engine makes (a released forecast) comes back as what changed, and lands in the working copy
  await page.goto("/#/demand/overview");
  const answer = page.waitForResponse((r) => r.url().includes("/api/forecast/release"));
  await page.getByRole("button", { name: "Use this forecast in the supply plan" }).click();
  const body = await (await answer).json();
  expect(body.dataset).toBeNull();
  expect([...Object.keys(body.patch.lists ?? {}), ...Object.keys(body.patch.set ?? {})]).toContain("demand");   // record by record, or the list
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/, { timeout: 15_000 });
  await page.goto("/#/demand");
  await expect(page.getByText(/Everything is up to date|out of date/).first()).toBeVisible();
  await expect(page.locator("main")).toContainText(/units over the next/);
});
