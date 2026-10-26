import { expect, test, type Page } from "@playwright/test";

// Enterprise 6.3, used the guide's way on Kaveri. Input: the orders due in the next ten days put on deliveries, the
// stock transfer of 600 kettles from Pune to Delhi late to leave, three carriers with their rates. Processing: what is
// waiting to load in vehicles by weight and volume, each lane carried the cheapest way; the transfer's freight order
// tendered, rejected, tendered to the next carrier, accepted, shipped and settled. Output: the vehicles and what the
// others would cost, the transfer dispatched and the delivery shipped, the bill against plan and what each carrier is
// owed. Engine: scp/transport.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const done = (page: Page) => page.locator('.banner[role="status"]').last();

test("loads built by weight and volume, the cheapest carrier, a rejection, the truck shipped and its bill settled", async ({ page }) => {
  test.setTimeout(240_000);
  await openKaveri(page);

  // input: the orders due in the next ten days on deliveries
  await page.goto("/#/selling/deliver");
  await page.getByLabel("Days ahead to ship").fill("10");
  await expect(page.getByRole("button", { name: /Make deliveries for \d+ lines/ })).toBeEnabled({ timeout: 45_000 });
  await page.getByRole("button", { name: /Make deliveries for \d+ lines/ }).click();
  await expect(done(page)).toContainText(/from Delhi NCR DC/, { timeout: 45_000 });

  // processing: the vehicles, each lane with the cheapest carrier
  await page.goto("/#/transport");
  await expect(page.getByRole("heading", { name: "Transport" })).toBeVisible();
  const vehicles = page.getByRole("table", { name: "Vehicles to load" });
  const sto = vehicles.getByRole("row", { name: /Pune plant/ });
  // 600 kettles, 780 kg: Sahyadri 24,000 + 1.20 a kg against Deccan's flat 32,000
  await expect(sto).toContainText("Sahyadri Freight Carriers", { timeout: 45_000 });
  await expect(sto).toContainText("₹24,936.00");
  await expect(sto).toContainText("Deccan Roadlines ₹32,000.00");
  await expect(sto).toContainText("late: STO-2201");
  const north = vehicles.getByRole("row", { name: /North trade distributors/ });
  // 500 grinders of 4.2 kg and 380 of 4.9: 3,962 kg at 3.20, 25.78 of Northline's 30 m³
  await expect(north).toContainText("Northline LTL Express");
  await expect(north).toContainText("3,962 kg");
  await expect(north).toContainText("86%");
  await expect(north).toContainText("₹12,678.40");
  await page.screenshot({ path: "test-results/transport-load.png", fullPage: true });
  await page.getByRole("button", { name: /^Make the \d+ freight orders/ }).click();
  await expect(done(page)).toContainText(/\d+ freight orders, INR/, { timeout: 30_000 });

  // the transfer's truck: Sahyadri turns it down, Deccan takes it
  await page.getByRole("tab", { name: /Freight orders/ }).click();
  const orders = page.getByRole("table", { name: "Freight orders" });
  const truck = orders.getByRole("row", { name: /Pune plant/ });
  const fo = (await truck.locator("td b").first().textContent())!.trim();
  await truck.getByRole("button", { name: `Tender ${fo}` }).click();
  await expect(done(page)).toContainText(`${fo} tendered to Sahyadri Freight Carriers for INR 24,936.00.`, { timeout: 30_000 });
  await truck.getByRole("button", { name: `Carrier rejected ${fo}` }).click();
  await expect(done(page)).toContainText(`Sahyadri Freight Carriers rejected ${fo}; tendered to Deccan Roadlines for INR 32,000.00 (+7,064.00).`, { timeout: 30_000 });
  await truck.getByRole("button", { name: `Carrier accepted ${fo}` }).click();
  await expect(done(page)).toContainText(`Deccan Roadlines accepted ${fo}`, { timeout: 30_000 });
  await truck.getByRole("button", { name: `Ship ${fo}` }).click();
  await expect(done(page)).toContainText(`${fo} left Pune plant (Chakan) for Delhi NCR DC on Mon 28 Sep with STO-2201.`, { timeout: 30_000 });

  // output: Deccan's bill, 1,150 over the plan, to pay in thirty days
  await truck.getByLabel(`Billed ${fo}`).fill("33150");
  await truck.getByLabel(`Bill number ${fo}`).fill("DR-5521");
  await truck.getByRole("button", { name: `Settle ${fo}` }).click();
  await expect(done(page)).toContainText(`${fo} settled (their DR-5521): INR 33,150.00, +1,150.00 against the planned INR 32,000.00; to pay by Wed 28 Oct.`, { timeout: 30_000 });
  await expect(truck).toContainText("settled");
  await expect(truck).toContainText("turned down by Sahyadri Freight Carriers");

  // the Delhi delivery goes by part load: shipping it is its goods issue
  const part = orders.getByRole("row", { name: /North trade distributors/ });
  const fo2 = (await part.locator("td b").first().textContent())!.trim();
  await part.getByRole("button", { name: `Tender ${fo2}` }).click();
  await expect(done(page)).toContainText(`${fo2} tendered to Northline LTL Express`, { timeout: 30_000 });
  await part.getByRole("button", { name: `Carrier accepted ${fo2}` }).click();
  await expect(done(page)).toContainText("accepted", { timeout: 30_000 });
  await part.getByRole("button", { name: `Ship ${fo2}` }).click();
  await expect(done(page)).toContainText(`${fo2} left Delhi NCR DC for North trade distributors`, { timeout: 30_000 });
  await page.screenshot({ path: "test-results/transport-orders.png", fullPage: true });

  // what each carrier carried and is owed
  await page.getByRole("tab", { name: /Carriers/ }).click();
  const carriers = page.getByRole("table", { name: "Carriers" });
  await expect(carriers.getByRole("row", { name: /Deccan Roadlines/ })).toContainText("₹33,150.00");
  await expect(carriers.getByRole("row", { name: /Sahyadri Freight Carriers/ })).toContainText("1");

  // on a phone the tables scroll in their own frame, the page does not
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/transport/orders");
  await expect(page.getByRole("table", { name: "Freight orders" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.setViewportSize({ width: 1280, height: 900 });

  // the delivery left: Selling shows it shipped
  await page.goto("/#/selling/deliver");
  await expect(page.getByText(/shipped/).first()).toBeVisible({ timeout: 30_000 });
});
