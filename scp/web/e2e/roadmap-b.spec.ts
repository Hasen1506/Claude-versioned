// Roadmap PR B: data entry (UX audit, 7 Oct 2026): spreadsheet paste, fill right and copy down in the demand grid, a
// stock-on-hand grid, a one-off purchase order, a bill of material without "planned at" first, plain labels, and buttons
// on the buy/ship cards that say which product and place they are for.
import { expect, test, type Locator, type Page } from "@playwright/test";

const fixture = {
  settings: { company_name: "Paste Works", planning_start: "2026-01-05", horizon_days: 28, default_calendar: "CAL" },
  calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4] }],
  locations: [{ id: "P", type: "plant", name: "Plant" }, { id: "D", type: "dc", name: "Depot" }, { id: "S", type: "supplier", name: "Supplier" }],
  products: [{ id: "A", type: "FG", name: "Alpha" }, { id: "B", type: "FG", name: "Beta" }, { id: "M", type: "RM", name: "Motor" },
    { id: "X", type: "FG", name: "Xeno" }],
  location_products: [{ location: "D", product: "A", on_hand: 0 }, { location: "D", product: "B", on_hand: 0 }],
  production_sources: [
    { id: "PV-A", location: "P", product: "A", fixed_lead_time_workdays: 1, components: [{ product: "M", qty: 1 }] },
    { id: "PV-B", location: "P", product: "B", fixed_lead_time_workdays: 1, components: [{ product: "M", qty: 2 }] },
  ],
  purchasing_sources: [{ id: "PIR-M", supplier: "S", product: "M", location: "P", price: 50, lead_time_days: 3 }],
  lanes: [{ id: "PD", origin: "P", destination: "D", modes: [{ transit_days: 1 }] }],
  demand: [
    { location: "D", product: "A", date: "2026-01-05", qty: 1, kind: "forecast", period_days: 7 },
    { location: "D", product: "B", date: "2026-01-05", qty: 1, kind: "forecast", period_days: 7 },
  ],
};

async function open(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Start with an empty company" }).click();
  await page.getByLabel("Company name").fill("Roadmap B");
  await page.getByRole("button", { name: "Create the company" }).click();
  await expect(page.getByRole("heading", { name: "Set up your company" })).toBeVisible();
  await page.getByRole("button", { name: "More", exact: true }).click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("menuitem", { name: "Import a dataset file…" }).click();
  await (await chooser).setFiles({ name: "f.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(fixture)) });
  await expect(page.locator(".topbar .company")).toHaveText("Paste Works");
}

/** Paste text as a spreadsheet puts it on the clipboard. */
const paste = (el: Locator, text: string) => el.evaluate((node, t) => {
  const dt = new DataTransfer();
  dt.setData("text/plain", t);
  node.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
}, text);

const values = (cells: Locator) => cells.evaluateAll((xs) => xs.map((x) => (x as HTMLInputElement).value));

test("demand grid: a block pasted from Excel fills rightwards and downwards in one undo step; Ctrl+R and Ctrl+D fill", async ({ page }) => {
  await open(page);
  await page.goto("/#/demand/plan");
  const alpha = page.locator("input.dp-in[aria-label^='Forecast of Alpha']");
  const beta = page.locator("input.dp-in[aria-label^='Forecast of Beta']");
  await expect(alpha).toHaveCount(4);
  await paste(alpha.first(), "10\t20\t1,250\n5\t6\t7\n");
  await expect(page.getByRole("status")).toContainText("6 cells filled");
  await expect.poll(() => values(alpha)).toEqual(["10", "20", "1250", ""]);
  await expect.poll(() => values(beta)).toEqual(["5", "6", "7", ""]);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect.poll(() => values(alpha)).toEqual(["1", "", "", ""]);
  await expect.poll(() => values(beta)).toEqual(["1", "", "", ""]);
  // fill right: the first week's value into every later week of the row
  await alpha.first().fill("8");
  await alpha.first().press("Control+r");
  await expect.poll(() => values(alpha)).toEqual(["8", "8", "8", "8"]);
  // copy down: the second week's value into the same week of every row below
  await alpha.nth(1).fill("9");
  await alpha.nth(1).press("Control+d");
  await expect.poll(() => values(beta)).toEqual(["1", "9", "", ""]);
});

test("stock on hand as one grid: paste a block, undo it", async ({ page }) => {
  await open(page);
  await page.goto("/#/material");
  await page.getByRole("button", { name: "Enter stock on hand as a grid" }).click();
  const cell = (prod: string, place: string) => page.getByLabel(`On hand of ${prod} at ${place}`, { exact: true });
  await paste(cell("Alpha", "Plant"), "100\t200\n300\t400");
  await expect(page.getByRole("status")).toContainText("4 cells filled");
  await expect(cell("Alpha", "Plant")).toHaveValue("100");
  await expect(cell("Alpha", "Depot")).toHaveValue("200");
  await expect(cell("Beta", "Plant")).toHaveValue("300");
  await expect(cell("Beta", "Depot")).toHaveValue("400");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(cell("Beta", "Depot")).toHaveValue("");
});

test("a one-off purchase order without a requisition", async ({ page }) => {
  await open(page);
  await page.goto("/#/buying/orders");
  await page.getByRole("button", { name: "New purchase order" }).click();
  await page.getByLabel("Quantity to buy").fill("12");
  await page.getByRole("button", { name: "Create the purchase order" }).click();
  await expect(page.getByRole("status").filter({ hasText: "PO-00001 created" })).toBeVisible();
  await expect(page.locator("tr", { hasText: "PO-00001" }).first()).toBeVisible();
});

test("a bill of material can be entered before the product is planned anywhere", async ({ page }) => {
  await open(page);
  await page.goto("/#/setup/product/X");
  await expect(page.getByText(/isn't needed anywhere yet/)).toBeVisible();
  await page.getByRole("button", { name: "Make it at Plant" }).click();
  await expect(page.getByRole("button", { name: "+ Add a part" })).toBeVisible();
});

test("buy and ship buttons name their product and place; a route back is refused; nothing is pre-picked", async ({ page }) => {
  await open(page);
  await page.goto("/#/setup/product/A/D");
  await expect(page.getByRole("button", { name: "Ship to Depot from another place" })).toBeVisible();
  await page.goto("/#/setup/product/M/P");
  await expect(page.getByRole("button", { name: "Add another supplier for Plant" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Make Motor/ })).toHaveCount(0);       // a raw material is bought
  // the plant ships Alpha to the depot already: a route from the depot back to the plant is refused
  await page.goto("/#/setup/product/A/P");
  await page.getByRole("button", { name: "Ship to Plant from another place" }).click();
  const from = page.locator(".wz-form label.qf", { hasText: "Ships from" }).locator("select");
  await expect(from).toHaveValue("");
  await from.selectOption("D");
  await expect(page.getByRole("alert")).toContainText("go round in a circle");
  await page.getByRole("button", { name: "Save the route to Plant" }).click();
  await page.goto("/#/data/lanes");
  await expect(page.getByText("D-P")).toHaveCount(0);
});
