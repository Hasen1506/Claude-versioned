import { expect, test, type Page } from "@playwright/test";

// Enterprise plan 5.3: one change swept over several sizes (cost against service), stored versions as columns of the
// side-by-side, and money at risk over time (engine: scp/whatif.py, sweep_chip and compare_scenarios).

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

test("a safety stock sweep is read as cost against expected service, and a size is kept as a version", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/whatif");
  await page.getByRole("tab", { name: "Sweep one change" }).click();
  await expect(page.getByLabel("Change to sweep")).toHaveValue("safety_days");
  await page.getByLabel("Sizes to try").fill("5");
  await expect(page.getByRole("alert")).toContainText("give two to eight numbers");
  await expect(page.getByRole("button", { name: "Sweep", exact: true })).toBeDisabled();
  await page.getByLabel("Sizes to try").fill("0, 2, 5, 10, 20");
  await page.getByRole("button", { name: "Sweep", exact: true }).click();
  const read = page.getByRole("list", { name: "What the sweep says" });
  await expect(read).toContainText(/From Safety stock 0 d to Safety stock 20 d: expected service .* % to .* %/, { timeout: 90_000 });
  await expect(read).toContainText("the plan itself takes the forecast as certain");
  await expect(read).toContainText("Not worth it:");
  await expect(page.getByRole("img", { name: "Cost against expected service" })).toBeVisible();
  const table = page.getByRole("table", { name: "Sweep" });
  await expect(table.locator("tbody tr")).toHaveCount(6);                 // today and five sizes
  await expect(table.locator("tbody tr").first()).toContainText("As today");
  await expect(table.getByRole("row", { name: /^Safety stock 5 d/ })).toContainText("worth it");
  await expect(table.getByRole("row", { name: /^Safety stock 20 d/ })).toContainText("not worth it");
  // money at risk over time follows the size picked
  await expect(page.getByRole("heading", { name: "Money at risk over time: today and Safety stock 20 d" })).toBeVisible();
  await table.getByRole("row", { name: /^Safety stock 5 d/ }).click();
  await expect(page.getByRole("heading", { name: "Money at risk over time: today and Safety stock 5 d" })).toBeVisible();
  await page.locator("section.panel", { has: read }).screenshot({ path: "test-results/whatif-sweep.png" });
  await table.getByRole("button", { name: "Keep Safety stock 5 d as a version" }).click();
  await expect(table.getByRole("row", { name: /^Safety stock 5 d/ })).toContainText(/Kept as V\d+/, { timeout: 30_000 });
});

test("any other change is read as an exposure: how far it can go before service falls", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/whatif");
  await page.getByRole("tab", { name: "Sweep one change" }).click();
  await page.getByLabel("Change to sweep").selectOption("lead_time");
  await expect(page.getByLabel("Sizes to try")).toHaveValue("-7, 7, 14, 21");
  await page.getByLabel("Supplier (every one if none)").selectOption("SUP-COPPER");
  await page.getByRole("button", { name: "Sweep", exact: true }).click();
  const read = page.getByRole("list", { name: "What the sweep says" });
  await expect(read).toContainText(/From Lead time -7 d at SUP-COPPER to Lead time \+21 d at SUP-COPPER: service/, { timeout: 90_000 });
  await expect(read).toContainText(/Service holds within half a point of today/);
  await expect(page.getByRole("img", { name: "Cost against on-time service" })).toBeVisible();
  const table = page.getByRole("table", { name: "Sweep" });
  await expect(table.locator("thead")).not.toContainText("Expected service");
  await expect(table).not.toContainText("worth it");
});

test("a stored version is a column of the side-by-side, and money at risk is shown by period", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/versions");
  await page.getByLabel("Version name").fill("Plan as is");
  await page.getByRole("button", { name: "Save as base version", exact: true }).click();
  await expect(page.locator(".version-chip")).toContainText("Plan as is · base");
  await page.goto("/#/whatif");
  await page.getByLabel("Name of scenario 2").fill("Busy season");
  await page.getByRole("button", { name: "Demand +20 %" }).click();
  const stored = page.getByLabel("Stored version");
  await stored.selectOption((await stored.locator("option", { hasText: "Plan as is" }).getAttribute("value"))!);
  await page.getByRole("button", { name: "+ Add it as a column" }).click();
  await expect(page.getByRole("group", { name: "Scenario Plan as is" })).toContainText(/stored version V\d+/);
  await page.getByRole("button", { name: "Compare side by side" }).click();
  const table = page.getByRole("table", { name: "What-if comparison" });
  await expect(table).toBeVisible({ timeout: 90_000 });
  await expect(table.locator("thead th").nth(3)).toContainText("Plan as is");
  await expect(table.getByRole("row", { name: /Changes/ })).toContainText(/stored version V\d+/);
  // the stored plan is the working copy as it was saved: no change against the baseline
  await expect(table.getByRole("row", { name: /Verdict/ }).locator("td").nth(3)).toContainText("same service");
  await expect(table.getByRole("row", { name: /Keep it/ }).locator("td").nth(3)).toContainText("a stored version");
  const risk = page.locator("section.panel", { has: page.getByRole("heading", { name: "Money at risk over time", exact: true }) });
  await expect(risk.getByRole("img")).toBeVisible();
  await risk.getByText("The figures by period").click();
  const byPeriod = risk.getByRole("table", { name: "Money at risk by period" });
  await expect(byPeriod.locator("thead")).toContainText("Busy season");
  await expect(byPeriod.getByRole("row", { name: /All periods/ })).toBeVisible();
  await risk.screenshot({ path: "test-results/whatif-versions.png" });
});

test("a supplier's price change is a chip: cost moves, service does not", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/whatif");
  await page.getByLabel("Name of scenario 2").fill("Copper dearer");
  await page.getByLabel("Supplier", { exact: true }).selectOption("SUP-COPPER");
  await page.getByLabel("Change of purchase prices in per cent").fill("10");
  await page.getByRole("button", { name: "Purchase prices at SUP-COPPER" }).click();
  await expect(page.getByLabel("Chips of Copper dearer")).toContainText("Purchase prices +10 % at SUP-COPPER");
  await page.getByRole("button", { name: "Compare side by side" }).click();
  const table = page.getByRole("table", { name: "What-if comparison" });
  await expect(table.getByRole("row", { name: /Changes/ })).toContainText("Purchase prices +10 % at SUP-COPPER", { timeout: 60_000 });
  // 10 % of the plan's copper buys; the firm winding order MO-100461 (7.1) adds ₹1,662 to the ₹15,00,619 without it
  await expect(table.getByRole("row", { name: /^Total plan cost/ }).locator("td").nth(2)).toContainText("+₹15.02 L");
  await expect(table.getByRole("row", { name: /Verdict/ }).locator("td").nth(2)).toContainText("same service");
});
