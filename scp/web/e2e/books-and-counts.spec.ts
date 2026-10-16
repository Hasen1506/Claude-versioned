import { expect, test, type Page } from "@playwright/test";

// Enterprise 6.2, used the guide's way on Kaveri. Input: stock kept at a moving average, the heating elements on
// PO-4500012871 received at Pune and billed dearer than ordered; the Delhi DC's products classed by what they used up.
// Processing: the receipt goes in at its landed cost, the invoice moves the average by the part still in stock; the
// products due for a cycle count go on a count document. Output: the heater's price in the books, the invoice among the
// postings, the count posted and its accuracy by class. Engine: scp/actuals/valuation, scp/actuals/cycle.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const heater = (page: Page) => page.getByRole("table", { name: "Stock value" }).getByRole("row", { name: /Concealed heating element/ });

test("stock in the books at a moving average: a receipt at landed cost, a dearer invoice moves it", async ({ page }) => {
  test.setTimeout(180_000);
  await openKaveri(page);

  // input: the company keeps its stock at a moving average
  await page.goto("/#/finance/books");
  await expect(page.getByText("Stock in the books", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
  await page.getByLabel("Price control").selectOption("moving_average");
  await expect(heater(page)).toContainText("moving average", { timeout: 30_000 });
  await expect(heater(page)).toContainText("14,000");

  // the heating elements arrive at Pune
  await page.goto("/#/buying/orders");
  await page.locator("tr.clickable", { hasText: "PO-4500012871" }).click();
  await page.getByRole("button", { name: "Receive goods" }).click();
  await page.getByLabel("Receive quantity PO-4500012871").fill("10000");
  await page.getByRole("button", { name: "Post goods receipt" }).click();
  await expect(page.locator(".banner.ok")).toContainText("Goods received on PO-4500012871", { timeout: 45_000 });

  // processing: at landed cost the receipt leaves the average where it was
  await page.goto("/#/finance/books");
  await expect(heater(page)).toContainText("24,000", { timeout: 30_000 });
  await expect(heater(page)).toContainText("141.65");

  // Shenzhen bills 1.50 USD an element against the order's price (the order, received in full, is among the closed)
  await page.goto("/#/buying/orders");
  await page.getByLabel("Show received and closed").check();
  await page.locator("tr.clickable", { hasText: "PO-4500012871" }).click();
  await page.getByRole("button", { name: "Enter the invoice" }).click();
  await page.getByLabel("Their invoice number").fill("SZ-771");
  await page.getByLabel("Billed price PO-4500012871").fill("1.5");
  await page.getByRole("button", { name: /^Enter the invoice \(\$15,/ }).click();   // in the supplier's dollars
  await expect(page.locator('.banner[role="status"]').last()).toContainText(/SI-00001 from Shenzhen electro-components \(their SZ-771\)/, { timeout: 45_000 });

  // output: the whole difference stays in stock (nothing has left it yet), the average up, the invoice among the postings
  await page.goto("/#/finance/books");
  await expect(heater(page)).toContainText("147.97", { timeout: 30_000 });
  await expect(heater(page)).toContainText("+₹6.31");
  await page.getByRole("tab", { name: /Postings/ }).click();
  await expect(page.getByRole("table", { name: "Valuation postings" }).getByRole("row", { name: /SI-00001/ }).first()).toContainText("Concealed heating element");
  await page.getByRole("tab", { name: /Price differences/ }).click();
  await page.screenshot({ path: "test-results/books.png", fullPage: true });
});

test("a cycle count by ABC class at the Delhi DC: what is due counted, one short, the accuracy by class", async ({ page }) => {
  test.setTimeout(180_000);
  await openKaveri(page);

  // input: the Delhi DC's products classed by what they used up
  await page.goto("/#/execution/count");
  await page.getByLabel("Place for cycle counts").selectOption({ label: "Delhi NCR DC" });
  const classes = page.getByRole("table", { name: "Cycle count classes" });
  await expect(classes.getByRole("row", { name: /^A / })).toContainText("2", { timeout: 30_000 });
  await expect(page.getByRole("table", { name: "Cycle count plan" })).toContainText("never");

  // processing: what is due goes on a count document, book stock frozen
  await page.getByRole("button", { name: "Count the 3 products due at Delhi NCR DC" }).click();
  await expect(page.locator('.banner[role="status"]').first()).toContainText("Cycle count: 2 A, 1 C.", { timeout: 30_000 });
  await expect(page.getByRole("table", { name: "Cycle count plan" })).toContainText("on PI-00001");
  await expect(page.getByRole("button", { name: /Nothing due at Delhi NCR DC/ })).toBeDisabled();

  // counted: two as booked, one grinder short
  await page.getByLabel("Counted KT-15 ").fill("1500");
  await page.getByLabel("Counted MG-500 ").fill("1498");
  await page.getByLabel("Counted MG-750 ").fill("900");
  await page.getByRole("button", { name: "Save 3 counts" }).click();
  await expect(page.getByRole("button", { name: "Post differences" })).toBeEnabled({ timeout: 30_000 });
  await page.getByRole("button", { name: "Post differences" }).click();

  // output: class A counted twice, one found as booked, two grinders less; nothing due any more
  const a = classes.getByRole("row", { name: /^A / });
  await expect(a).toContainText("50%", { timeout: 30_000 });
  await expect(a).toContainText("−₹");
  await expect(classes.getByRole("row", { name: /^C / })).toContainText("100%");
  await expect(page.getByRole("button", { name: /Nothing due at Delhi NCR DC/ })).toBeVisible();
  await page.screenshot({ path: "test-results/cycle-counts.png", fullPage: true });
});
