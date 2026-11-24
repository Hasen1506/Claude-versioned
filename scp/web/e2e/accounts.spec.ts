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

function dinarInventory(company_name: string) {
  return {
    settings: { company_name, currency: "KWD", planning_start: "2026-01-05", horizon_days: 28,
      default_calendar: "CAL" },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "P", type: "plant" }, { id: "S", type: "supplier" }],
    products: [{ id: "B", type: "RM" }],
    location_products: [{ location: "P", product: "B", on_hand: 0 }],
    execution: { price_control: "moving_average" },
    purchasing_sources: [{ id: "BUY-B", supplier: "S", location: "P", product: "B", price: 1.2345, lead_time_days: 1 }],
    receipts: [{ id: "PO-LINE", kind: "purchase", location: "P", product: "B", qty: 2, price: 1.2345,
      due_date: "2026-01-06", source: "BUY-B" }],
    movements: [{ id: "R-1", date: "2026-01-06", type: "receipt", reference: "PO-LINE", location: "P", product: "B", qty: 2 }],
  };
}

test("the dinar purchasing accrual, material trial balance and CSV keep three decimal places", async ({ page }) => {
  const data = dinarInventory("Dinar inventory");
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "dinar-stock.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(data)) });
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/buying/owed");
  const accrued = page.locator(".tile").filter({ hasText: "Received, not invoiced" });
  await expect(accrued.getByText("KWD 2.469", { exact: true })).toBeVisible();
  await page.goto("/#/accounts");
  const balances = page.getByRole("table", { name: "Trial balance" });
  await expect(balances.getByRole("row", { name: /^Stock/ })).toContainText("KWD 2.469");
  await page.getByRole("tab", { name: "Tally" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download the journal (CSV)", exact: true }).click();
  const content = readFileSync((await (await download).path())!, "utf8");
  expect(content).toContain(",2.469,0.000");
  expect(content).toContain(",0.000,2.469");
});

test("a live dinar supplier invoice survives retry and reopens its exact accrual on cancellation", async ({ page, request }) => {
  const email = `dinar-invoice-${Date.now()}@example.invalid`;
  const password = "fixture-only-dinar-autumn";
  const created = await request.post("/api/auth/signup", { data: { email, password, name: "Accounts clerk" } });
  expect(created.ok(), await created.text()).toBe(true);
  const headers = { Authorization: `Bearer ${(await created.json()).token}` };
  const company = await request.post("/api/companies", { headers, data: { dataset: dinarInventory("Dinar invoice fixture") } });
  expect(company.ok(), await company.text()).toBe(true);
  const path = `/api/companies/${(await company.json()).id}`;
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Sign in", exact: true }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: /Open Dinar invoice fixture/ }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/buying/invoices");
  const entryAttempts: string[] = [];
  const cancellationAttempts: string[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const body = route.request().postDataJSON();
    const attempts = body.action === "enter_invoice" ? entryAttempts
      : body.action === "cancel_invoice" ? cancellationAttempts : null;
    if (!attempts) return route.continue();
    attempts.push(body.id);
    if (attempts.length !== 1) return route.continue();
    const posted = await route.fetch();
    expect(posted.ok(), await posted.text()).toBe(true);
    return route.abort("failed");
  });
  await expect(page.getByLabel("Invoice date")).toHaveValue("2026-01-06");
  await page.getByLabel("Their invoice number").fill("KWD-SUPPLIER-1");
  await page.getByLabel("Billed quantity PO-LINE").fill("1");
  await page.getByLabel("Tax charged").fill("0.001");
  const enter = page.getByRole("button", { name: "Enter the invoice (KWD 1.236)" });
  await enter.click();
  await expect(page.getByRole("alert")).toContainText("Confirmation is unavailable");
  await expect(enter).toBeDisabled();
  await page.reload();
  await page.getByRole("button", { name: "Retry invoice", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "SI-00001" })).toContainText("KWD 1.236");
  expect(entryAttempts).toHaveLength(2);
  expect(entryAttempts[1]).toBe(entryAttempts[0]);
  const accrued = page.locator(".tile").filter({ hasText: "Received, not invoiced" });
  await expect(accrued).toContainText("KWD 1.234");
  await page.getByRole("row", { name: /SI-00001.*KWD-SUPPLIER-1/ }).click();
  await expect(page.getByRole("button", { name: "Record payment (KWD 1.236)" })).toBeVisible();
  await page.getByLabel("Cancellation date").fill("2026-01-07");
  await page.getByRole("button", { name: "Cancel it", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Confirmation is unavailable");
  await page.reload();
  await page.getByRole("button", { name: "Retry cancellation", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "SI-00001 cancelled" })).toBeVisible();
  await expect(accrued).toContainText("KWD 2.469");
  expect(cancellationAttempts).toHaveLength(2);
  expect(cancellationAttempts[1]).toBe(cancellationAttempts[0]);
  const saved = await (await request.get(path, { headers })).json();
  expect(saved.meta.revision).toBe(3);
  expect(saved.dataset.supplier_invoices).toMatchObject([{ id: "SI-00001", currency: "KWD",
    cancelled_on: "2026-01-07", cancelled_after: 1 }]);
});

test("a one-fils supplier payment and its reversal both recover after a reload", async ({ page, request }) => {
  const email = `dinar-payment-${Date.now()}@example.invalid`;
  const password = "fixture-only-dinar-payment";
  const session = await request.post("/api/auth/signup", { data: { email, password, name: "Treasury clerk" } });
  expect(session.ok(), await session.text()).toBe(true);
  const headers = { Authorization: `Bearer ${(await session.json()).token}` };
  const fixture = dinarInventory("Dinar payment fixture");
  fixture.receipts[0].price = fixture.purchasing_sources[0].price = 0.001;
  const created = await request.post("/api/companies", { headers, data: { dataset: fixture } });
  expect(created.ok(), await created.text()).toBe(true);
  const company = `/api/companies/${(await created.json()).id}`;
  const issued = await request.post(`${company}/commands`, { headers, data: {
    kind: "purchasing", action: "enter_invoice", id: "fixture-invoice", base_revision: 1, posting_date: "2026-01-06",
    parameters: { reference: "ONE-FILS", lines: [{ order: "PO-LINE", qty: 1 }] },
  } });
  expect(issued.ok(), await issued.text()).toBe(true);
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Sign in", exact: true }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: /Open Dinar payment fixture/ }).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/buying/invoices/SI-00001");

  const attempts: Record<string, string[]> = { pay_invoice: [], reverse_invoice_payment: [] };
  await page.route("**/api/companies/*/commands", async (route) => {
    const body = route.request().postDataJSON();
    const ids = attempts[body.action];
    if (!ids) return route.continue();
    ids.push(body.id);
    if (ids.length > 1) return route.continue();
    const committed = await route.fetch();
    expect(committed.ok(), await committed.text()).toBe(true);
    return route.abort("failed");
  });

  await page.getByLabel("Bank reference").fill("WIRE-001");
  await page.getByLabel("Paid on").fill("2026-01-07");
  await page.getByRole("button", { name: "Record payment (KWD 0.001)", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(/confirmation is unavailable/i);
  await page.reload();
  await page.getByRole("button", { name: "Retry payment", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("KWD 0.001 recorded");
  await expect(page.getByText(/Payment 1 · KWD 0.001/)).toBeVisible();

  await page.getByLabel("Payment to reverse").selectOption("1");
  await page.getByLabel("Reversal date").fill("2026-01-08");
  await page.getByLabel("Reversal reason").fill("Transfer returned");
  await page.getByRole("button", { name: "Reverse payment", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Confirmation is unavailable");
  await page.reload();
  await page.getByRole("button", { name: "Retry payment reversal", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("reversed");
  await expect(page.getByText(/Reversal of payment 1 · KWD 0.001/)).toBeVisible();
  const owed = page.locator(".tile").filter({ hasText: "We owe" });
  await expect(owed).toContainText("KWD 0.001");

  const stored = await (await request.get(company, { headers })).json();
  expect(stored.meta.revision).toBe(4);
  expect(stored.dataset.supplier_invoices[0].payments).toMatchObject([
    { date: "2026-01-07", amount: 0.001, reference: "WIRE-001" },
    { date: "2026-01-08", amount: 0.001, reverses: 1, reason: "Transfer returned" },
  ]);
  for (const ids of Object.values(attempts)) {
    expect(ids).toHaveLength(2);
    expect(ids[1]).toBe(ids[0]);
  }
});

test("a KWD supplier statement ties to its posted bank voucher after a lost match response", async ({ page, request }) => {
  const email = `supplier-bank-${Date.now()}@example.invalid`;
  const password = "fixture-only-supplier-bank";
  const session = await request.post("/api/auth/signup", { data: { email, password, name: "Bank clerk" } });
  expect(session.ok(), await session.text()).toBe(true);
  const headers = { Authorization: `Bearer ${(await session.json()).token}` };
  const fixture = dinarInventory("Supplier bank fixture");
  fixture.receipts[0].price = fixture.purchasing_sources[0].price = 0.001;
  const created = await request.post("/api/companies", { headers, data: { dataset: fixture } });
  expect(created.ok(), await created.text()).toBe(true);
  const path = `/api/companies/${(await created.json()).id}`;
  const issued = await request.post(`${path}/commands`, { headers, data: {
    kind: "purchasing", action: "enter_invoice", id: "fixture-invoice", base_revision: 1, posting_date: "2026-01-06",
    parameters: { reference: "ONE-FILS", lines: [{ order: "PO-LINE", qty: 1 }] },
  } });
  expect(issued.ok(), await issued.text()).toBe(true);
  const opened = await request.post(`${path}/commands`, { headers, data: {
    kind: "carrier_bank", action: "record", id: "fixture-bank", base_revision: 2, posting_date: "2026-01-08",
    parameters: { event: { kind: "register_account", id: "KWD-A", company: "", starts_on: "2026-01-08", opening_minor: 1000 } },
  } });
  expect(opened.ok(), await opened.text()).toBe(true);

  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Sign in", exact: true }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: /Open Supplier bank fixture/ }).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/buying/invoices/SI-00001");
  await page.getByLabel("Paid on").fill("2026-01-08");
  await expect(page.getByLabel("Payment bank account")).toHaveValue("KWD-A");
  await page.getByLabel("Bank reference").fill("DRAFT-TRANSFER-1");
  await page.getByRole("button", { name: "Record payment (KWD 0.001)", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "recorded on SI-00001" })).toBeVisible();
  await page.getByRole("link", { name: "Supplier bank reconciliation", exact: true }).click();
  await page.getByText("Import account statement period", { exact: true }).click();
  await page.getByLabel("Statement period account").selectOption("KWD-A");
  await page.getByLabel("Statement number").fill("KWD-08");
  await page.getByLabel("Statement period start").fill("2026-01-08");
  await page.getByLabel("Statement period end").fill("2026-01-08");
  await page.getByLabel("Statement period opening balance").fill("1.000");
  await page.getByLabel("Statement period closing balance").fill("0.999");
  await page.getByLabel("Source rows").fill("1");
  await page.getByLabel("Statement period CSV").setInputFiles({ name: "kwd-period.csv", mimeType: "text/csv",
    buffer: Buffer.from("line,date,reference,amount,currency\nKWD-ENTRY,2026-01-08,DRAFT-TRANSFER-1,-0.001,KWD\n") });
  await page.getByRole("button", { name: "Import period", exact: true }).click();
  const reconciliation = page.getByRole("table", { name: "Supplier bank account reconciliation", exact: true });
  await expect(reconciliation).toContainText("Review differences");
  await page.getByRole("button", { name: "KWD-ENTRY", exact: true }).click();
  await page.getByLabel("Recorded supplier cash").selectOption("SI-00001/1");

  const attempts: string[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const data = route.request().postDataJSON();
    if (data.parameters?.event?.kind !== "match_supplier_payment") return route.continue();
    attempts.push(data.id);
    if (attempts.length > 1) return route.continue();
    const committed = await route.fetch();
    expect(committed.ok(), await committed.text()).toBe(true);
    return route.abort("failed");
  });
  await page.getByRole("button", { name: "Match supplier cash", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(/confirmation is unavailable/i);
  await page.reload();
  await page.getByRole("button", { name: "Retry statement operation", exact: true }).click();
  await expect(reconciliation).toContainText("Reconciled");
  await expect(reconciliation.getByText("KWD 0.999", { exact: true })).toHaveCount(2);
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toBe(attempts[0]);
  const company = await (await request.get(path, { headers })).json();
  expect(company.meta.revision).toBe(6);
  expect(company.dataset.supplier_invoices[0].payments).toMatchObject([{ amount: 0.001, bank_account: "KWD-A" }]);
  expect(company.dataset.carrier_bank_lines[0].history).toMatchObject([
    { targets: [], supplier_payment: { invoice: "SI-00001", payment_number: 1 } },
  ]);
});
