import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

// Enterprise 7.4, used the guide's way on Kaveri. Input: the company as it ships — opening stock, two deliveries
// not invoiced yet, the Delhi DC in its own company. Processing: the deliveries are invoiced on Selling and one
// customer pays. Output: each company's trial balance and who owes what, the journal with the invoice's voucher,
// every check against the documents agreeing, and Tally's import file with the ledger name given here.
// Engine: scp/accounting.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const num = (t: string) => Number(t.replace(/[^\d.-]/g, ""));

test("production costs are posted once after a lost response and settled from the order's WIP", async ({ page }) => {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "costs.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify({
    schema_version: "1",
    settings: { company_name: "Manufacturing cost fixture", planning_start: "2026-01-05", horizon_days: 28, default_calendar: "CAL" },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "P", type: "plant" }],
    products: [{ id: "A", type: "FG", standard_cost: 10 }, { id: "B", type: "RM", standard_cost: 4 }],
    location_products: [{ location: "P", product: "A", on_hand: 0 }, { location: "P", product: "B", on_hand: 0 }],
    resources: [], lanes: [], purchasing_sources: [], demand: [], history: [],
    production_sources: [{ id: "MAKE-A", location: "P", product: "A", output_qty: 1,
      components: [{ product: "B", qty: 2 }], conversion_cost_per_unit: 2 }],
    receipts: [{ id: "MO-1", kind: "production", location: "P", product: "A", qty: 10,
      due_date: "2026-01-06", source: "MAKE-A" }],
    movements: [
      { id: "OPEN-1", date: "2026-01-04", type: "opening", location: "P", product: "B", qty: 100 },
      { id: "MOVE-1", date: "2026-01-06", type: "issue", location: "P", product: "B", qty: 20, reference: "MO-1" },
      { id: "MOVE-2", date: "2026-01-06", type: "receipt", location: "P", product: "A", qty: 10, reference: "MO-1", final: true },
    ],
  })) });
  await expect(page.locator(".topbar .company")).toHaveText("Manufacturing cost fixture");
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`cost-owner-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Cost accountant");
  await page.getByLabel(/^Password/).fill("fixture-only-forest-line");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  await page.goto("/#/accounts/production");
  const order = page.getByRole("table", { name: "Work in progress by production order" }).getByRole("row", { name: /MO-1/ });
  await expect(order).toContainText("20.00 Cr");
  await page.getByLabel("Production order", { exact: true }).selectOption("MO-1");
  await page.getByLabel("Source or review reference").fill("LABOR-12");
  await page.getByLabel(/Actual conversion cost/).fill("26.00");

  const requests: string[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const body = route.request().postDataJSON();
    if (body.action === "conversion") {
      requests.push(body.id);
      if (requests.length === 1) {
        const committed = await route.fetch();
        expect(committed.ok()).toBe(true);
        return route.abort("failed");
      }
    }
    return route.continue();
  });
  const convert = page.getByRole("button", { name: "Post conversion cost" });
  await convert.click();
  await expect(page.getByRole("alert")).toBeVisible();
  await convert.click();
  await expect(order).toContainText("6.00 Dr");
  expect(requests).toHaveLength(2);
  expect(requests[0]).toBe(requests[1]);
  await page.getByLabel("Source or review reference").fill("COST-REVIEW-1");
  await page.getByLabel("Actual costs reviewed").check();
  await page.getByRole("button", { name: "Settle WIP" }).click();
  await expect(order).toContainText("PC-");
  await expect(order.locator("td").nth(4)).toHaveText("0");
  await page.reload();
  await expect(order.locator("td").nth(4)).toHaveText("0");
});

test("the books follow the invoices and payments, check themselves and go to Tally", async ({ page }) => {
  test.setTimeout(180_000);
  await openKaveri(page);

  // input: the books as the company ships
  await page.goto("/#/accounts");
  await expect(page.getByRole("heading", { name: "Accounts" })).toBeVisible();
  const tb = page.getByRole("table", { name: "Trial balance" });
  await expect(tb.getByRole("row", { name: /Opening balances/ })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/2 deliveries are not invoiced yet/)).toBeVisible();

  // processing: invoice what was delivered, and the first customer pays
  await page.goto("/#/selling/bill");
  await page.getByLabel("Invoice date").fill("2026-10-03");
  await page.getByRole("button", { name: /^Invoice ₹/ }).click();
  await expect(page.getByText(/INV-00001 to .*INV-00002 to/)).toBeVisible({ timeout: 30_000 });
  const rowOf = (id: string) => page.locator("tr.clickable", { hasText: id });
  const total1 = num(await rowOf("INV-00001").locator("td").nth(4).innerText());
  const total2 = num(await rowOf("INV-00002").locator("td").nth(4).innerText());
  await rowOf("INV-00001").click();
  await page.getByLabel("Paid on").fill("2026-10-05");
  await page.getByLabel("Bank reference").fill("UTR-55");
  await page.getByRole("button", { name: "Payment received" }).click();
  await expect(page.getByText(/received for INV-00001 .*settled/)).toBeVisible({ timeout: 30_000 });

  // output: the main company was paid; the Delhi company's customer still owes its invoice
  await page.goto("/#/accounts");
  await expect(page.getByText(/2 deliveries are not invoiced yet/)).toHaveCount(0, { timeout: 30_000 });
  const sales = page.locator(".tile", { hasText: "Sales to date" });
  await expect(sales).toBeVisible();
  const bank = tb.getByRole("row", { name: /^Bank/ });
  expect(num(await bank.locator("td").nth(4).innerText())).toBeCloseTo(total1, 1);
  await page.getByLabel("Company").selectOption({ label: "Kaveri Appliances North Pvt Ltd (fictional)" });
  await page.getByRole("tab", { name: /Who owes what/ }).click();
  const owes = page.getByRole("table", { name: "Who owes what" }).getByRole("row", { name: /North trade distributors/ });
  expect(num(await owes.locator("td").nth(2).innerText())).toBeCloseTo(total2, 1);

  // the journal has the invoice's voucher and the payment's, the customer debited and credited its total
  await page.getByLabel("Company").selectOption({ label: "Kaveri Kitchenware Pvt Ltd (fictional)" });
  await page.getByRole("tab", { name: /Journal/ }).click();
  await page.getByLabel("Find a voucher").fill("INV-00001");
  const journal = page.getByRole("table", { name: "Journal" });
  const debtor = journal.getByRole("row", { name: /Customers/ });
  await expect(debtor).toHaveCount(2);                 // the invoice's debit, the payment's credit
  const cells = await Promise.all([0, 1].map(async (i) => [num(await debtor.nth(i).locator("td").nth(-2).innerText()),
    num(await debtor.nth(i).locator("td").nth(-1).innerText())]));
  expect(cells.map(([dr, cr]) => dr - cr).sort((a, b) => a - b)).toEqual([-total1, total1]);

  // every check agrees with the documents
  await page.getByRole("tab", { name: /Checks/ }).click();
  const checks = page.getByRole("table", { name: "Checks" });
  await expect(checks.getByText("agrees").first()).toBeVisible();
  await expect(checks.getByText("differs")).toHaveCount(0);

  // Tally: the bank ledger under its name in Tally, in the file
  await page.getByRole("tab", { name: /Tally/ }).click();
  await page.getByLabel("Tally ledger for Bank", { exact: true }).fill("HDFC Bank 50200");
  await page.getByLabel("Company name in Tally").fill("Kaveri Kitchenware FY27");
  const dl = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download the Tally file" }).click();
  const xml = readFileSync((await (await dl).path())!, "utf8");
  expect(xml).toContain("<SVCURRENTCOMPANY>Kaveri Kitchenware FY27</SVCURRENTCOMPANY>");
  expect(xml).toContain("<LEDGERNAME>HDFC Bank 50200</LEDGERNAME>");
  expect(xml).toContain('<LEDGER NAME="West trade distributors" ACTION="Create">');
  expect(xml).toMatch(/<VOUCHER VCHTYPE="Sales" ACTION="Create"><DATE>20261003<\/DATE>/);
  const dl2 = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download the journal (CSV)" }).click();
  const csv = readFileSync((await (await dl2).path())!, "utf8");
  expect(csv).toMatch(/INV-00001.*Customers|Customers.*INV-00001/s);
  await page.screenshot({ path: "test-results/accounts.png", fullPage: true });
});

test("the accounts downloads retain two registered bank destinations", async ({ page }) => {
  const company = {
    settings: { company_name: "Bank export fixture", planning_start: "2026-03-06", horizon_days: 28, currency: "INR" },
    entities: [{ id: "E1", name: "Paying company" }, { id: "E2", name: "Other company" }],
    locations: [{ id: "W", type: "dc", entity: "E1" }, { id: "C", type: "customer" }],
    lanes: [{ id: "L", origin: "W", destination: "C", modes: [{ mode: "truck_ftl", transit_days: 1 }] }],
    carriers: [{ id: "CR", rates: [{ lane: "L", per_shipment: 90 }] }],
    carrier_bank_accounts: [
      { id: "BANK-A", company: "E1", starts_on: "2026-03-01", opening_minor: 20_000, currency: "INR" },
      { id: "BANK-B", company: "E1", starts_on: "2026-03-01", opening_minor: 30_000, currency: "INR" },
      { id: "BANK-C", company: "E2", starts_on: "2026-03-01", opening_minor: 10_000, currency: "INR" },
    ],
    freight_orders: [40.25, 59.75].map((amount, index) => ({
      id: `FO-${index + 1}`, lane: "L", mode: "truck_ftl", carrier: "CR", ship_from: "W", ship_to: "C", status: "settled",
      planned_on: "2026-03-02", shipped_on: "2026-03-02", settled_on: "2026-03-02", billed: amount, bill: `BILL-${index + 1}`,
      deliveries: [`DL-${index + 1}`],
      bill_payments: [{ date: "2026-03-03", amount, reference: `WIRE-${index + 1}`, bank_account: index === 0 ? "BANK-A" : "BANK-B" }],
    })),
  };
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "bank-export.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`bank-export-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Accountant");
  await page.getByLabel(/^Password/).fill("fixture-only-spring-clover");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  await page.goto("/#/accounts/tally");
  await page.getByLabel("Company", { exact: true }).selectOption("E1");
  const tally = page.getByRole("button", { name: "Download bank-detail Tally file" });
  await expect(page.getByLabel("Tally bank ledger for BANK-C", { exact: true })).toHaveCount(0);
  await tally.click();
  await expect(page.getByRole("alert")).toContainText("BANK-A, BANK-B");
  await page.getByLabel("Tally bank ledger for BANK-A", { exact: true }).fill("Primary & Co");
  await page.getByLabel("Tally bank ledger for BANK-B", { exact: true }).fill("Reserve Bank");
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  await page.reload();
  await page.getByLabel("Company", { exact: true }).selectOption("E1");
  await expect(page.getByLabel("Tally bank ledger for BANK-A", { exact: true })).toHaveValue("Primary & Co");
  await expect(page.getByLabel("Tally bank ledger for BANK-B", { exact: true })).toHaveValue("Reserve Bank");
  const xmlDownload = page.waitForEvent("download");
  await tally.click();
  const xml = readFileSync((await (await xmlDownload).path())!, "utf8");
  expect(xml).toMatch(/<VOUCHERNUMBER>FO-1\/P-1<\/VOUCHERNUMBER>(?:(?!<\/VOUCHER>).)*<LEDGERNAME>Primary &amp; Co<\/LEDGERNAME>/);
  expect(xml).toMatch(/<VOUCHERNUMBER>FO-2\/P-1<\/VOUCHERNUMBER>(?:(?!<\/VOUCHER>).)*<LEDGERNAME>Reserve Bank<\/LEDGERNAME>/);
  expect(xml).not.toContain('<LEDGER NAME="Reserve Bank"');
  const csvDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download bank-detail CSV" }).click();
  const csv = readFileSync((await (await csvDownload).path())!, "utf8");
  expect(csv.split(/\r?\n/)[0]).toMatch(/,company_id,bank_account$/);
  expect(csv).toMatch(/FO-1\/P-1.*E1,BANK-A/);
  expect(csv).toMatch(/FO-2\/P-1.*E1,BANK-B/);
});
