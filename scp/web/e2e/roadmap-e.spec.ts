// Roadmap PR E: what-if side by side (UX audit, section 4). Scenarios are built from chips on the working copy and
// compared with the baseline in one table.
import { expect, test, type Page } from "@playwright/test";

async function openExample(page: Page, name: string) {
  await page.goto("/");
  await page.getByText(name).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

test("chips build scenarios that are compared side by side against the baseline", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: "What if… side by side" }).click();
  await expect(page.getByRole("heading", { name: "What if… side by side" })).toBeVisible();

  // scenario 1: demand +20 %
  await page.getByLabel("Name of scenario 2").fill("Busy season");
  await page.getByRole("button", { name: "Demand +20 %" }).click();
  await expect(page.getByLabel("Chips of Busy season")).toContainText("Demand +20 %");

  // scenario 2: a supplier out and the routes via the plant held up
  await page.getByRole("button", { name: "+ Add a scenario" }).click();
  await page.getByLabel("Name of scenario 3").fill("Trouble");
  await page.getByLabel("Supplier", { exact: true }).selectOption("SUP-COPPER");
  await page.getByRole("button", { name: "Supplier out" }).click();
  await page.getByLabel("Place on the routes").selectOption("PLT-PUNE");
  await page.getByLabel("Route delay in days").fill("5");
  await page.getByRole("button", { name: "Delay routes" }).click();
  await expect(page.getByLabel("Chips of Trouble")).toContainText("SUP-COPPER out");
  await expect(page.getByLabel("Chips of Trouble")).toContainText("Routes via PLT-PUNE +5 d");

  // a chip comes off again
  await page.getByRole("button", { name: "Demand -10 %" }).click();
  await page.getByRole("button", { name: "Remove Demand -10 % from Trouble" }).click();
  await expect(page.getByLabel("Chips of Trouble")).not.toContainText("Demand -10 %");

  await page.getByRole("button", { name: "Compare side by side" }).click();
  const table = page.getByRole("table", { name: "What-if comparison" });
  await expect(table).toBeVisible({ timeout: 60_000 });
  const head = table.locator("thead th");
  await expect(head.nth(1)).toContainText("Baseline");
  await expect(head.nth(2)).toContainText("Busy season");
  await expect(head.nth(3)).toContainText("Trouble");
  await expect(table.getByRole("row", { name: /Changes/ })).toContainText("Demand +20 %");
  await expect(table.getByRole("row", { name: /Changes/ })).toContainText("SUP-COPPER out · Routes via PLT-PUNE +5 d");
  await expect(table.getByRole("row", { name: /Total plan cost/ })).toBeVisible();
  await expect(table.getByRole("row", { name: /On-time service/ })).toContainText("pts");
  await expect(table.getByRole("row", { name: /Verdict/ })).toContainText(/trade-off|worse on both|better on both|same service/);
  await expect(table.getByText("lowest cost")).toBeVisible();
  // the copper supplier is the only one for its wire: the scenario still plans and says so
  await expect(table.getByRole("row", { name: /Verdict/ })).toContainText("No other supplier");
});

test("every scenario needs its own name, and the working copy is not changed", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/whatif");
  await page.getByLabel("Name of scenario 2").fill("Baseline");
  await expect(page.getByRole("button", { name: "Compare side by side" })).toBeDisabled();
  await expect(page.getByText("give every scenario its own name")).toBeVisible();
  await page.getByLabel("Name of scenario 2").fill("Extra shift");
  await page.getByLabel("Machine or line").selectOption("PUNE-L1");
  await page.getByRole("button", { name: "Add a shift" }).click();
  await page.getByRole("button", { name: "Compare side by side" }).click();
  await expect(page.getByRole("table", { name: "What-if comparison" })).toContainText("Add a shift on PUNE-L1", { timeout: 60_000 });
  // nothing to save: the data was never edited
  await page.goto("/#/home");
  await expect(page.getByText(/Everything is up to date/)).toBeVisible();
});

test("a machine down, one customer's prices, safety stock in days and the dollar; the winner kept as a version", async ({ page }) => {
  await openExample(page, "Kaveri Kitchenware");
  await page.goto("/#/whatif");
  await expect(page.getByRole("heading", { name: "What if… side by side" })).toBeVisible();

  // scenario 1: the assembly line out for two weeks
  await page.getByLabel("Name of scenario 2").fill("Line down");
  await page.getByLabel("Machine or line").selectOption("PUNE-L1");
  await page.getByLabel("Days the machine is down").fill("14");
  await page.getByRole("button", { name: "PUNE-L1 down" }).click();
  await expect(page.getByLabel("Chips of Line down")).toContainText("PUNE-L1 down 14 d");

  // scenario 2: the web shop pays 10 % more, ten days of safety stock and a dearer dollar
  await page.getByRole("button", { name: "+ Add a scenario" }).click();
  await page.getByLabel("Name of scenario 3").fill("Dearer web shop");
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-ECOM");
  await page.getByLabel("Price change in per cent").fill("10");
  await page.getByRole("button", { name: "Price change for the customer" }).click();
  await page.getByLabel("Safety stock in days").fill("10");
  await page.getByRole("button", { name: "Safety stock in days" }).click();
  await page.getByLabel("Currency", { exact: true }).selectOption("USD");
  await page.getByLabel("Exchange rate change in per cent").fill("20");
  await page.getByRole("button", { name: "Exchange rate move" }).click();
  const chips = page.getByLabel("Chips of Dearer web shop");
  await expect(chips).toContainText("Prices +10 % for CUS-ECOM");
  await expect(chips).toContainText("Safety stock 10 d");
  await expect(chips).toContainText("USD +20 %");

  await page.getByRole("button", { name: "Compare side by side" }).click();
  const table = page.getByRole("table", { name: "What-if comparison" });
  await expect(table).toBeVisible({ timeout: 60_000 });
  // the price change shows as more sales value; the line down costs service
  await expect(table.locator("tr", { hasText: "Sales value" })).toContainText("+");
  await expect(table.locator("tr", { hasText: "On-time service" })).toContainText("pts");

  // keep the first scenario: the working copy is stored as a base, the scenario is its branch with the chip in it
  await page.getByRole("button", { name: "Keep Line down as a version" }).click();
  await expect(table.locator("tr", { hasText: "Keep it" })).toContainText(/Kept as V\d+/);
  await table.getByRole("link", { name: "open it in Versions" }).click();
  await expect(page.locator("main")).toContainText("Line down");
});
