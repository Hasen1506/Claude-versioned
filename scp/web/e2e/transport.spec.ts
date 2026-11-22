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

test("live carrier billing, credit and AP payment recover after reload", async ({ page }) => {
  const shipped = "2026-01-06";
  const date = "2026-01-07";
  const company = {
    settings: { company_name: "Carrier bill fixture", planning_start: "2026-01-05", horizon_days: 28 },
    locations: [{ id: "P", type: "plant", entity: "E1" }, { id: "C", type: "customer" }],
    entities: [{ id: "E1", name: "Posting entity" }],
    lanes: [{ id: "L", origin: "P", destination: "C", modes: [{ mode: "truck_ftl", transit_days: 1 }] }],
    carriers: [{ id: "CR", name: "Fixture Carrier", rates: [{ lane: "L", per_shipment: 90 }] }],
    freight_orders: [{ id: "FO-1", lane: "L", mode: "truck_ftl", carrier: "CR", ship_from: "P", ship_to: "C",
      planned_on: shipped, shipped_on: shipped, status: "shipped", planned_cost: 90,
      deliveries: ["DL-1", "DL-2", "DL-3"], weights: { "DL-1": 100, "DL-2": 100, "DL-3": 100 } }],
  };
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "freight.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`carrier-billing-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Freight accounts");
  await page.getByLabel(/^Password/).fill("fixture-only-spring-clover");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  await page.goto("/#/transport/orders");

  let companyUrl = "";
  const requests: { id: string; kind: string; action: string; posting_date: string; parameters: object }[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    requests.push(route.request().postDataJSON());
    if ([1, 3, 6].includes(requests.length)) {
      companyUrl = route.request().url().replace(/\/commands$/, "");
      const committed = await route.fetch();
      expect(committed.ok(), await committed.text()).toBe(true);
      return route.abort("failed");
    }
    await route.continue();
  });
  await expect(page.getByLabel("Posting date FO-1")).toHaveValue(shipped);
  await page.getByLabel("Posting date FO-1").fill(date);
  await page.getByLabel("Billed FO-1").fill("100");
  await page.getByLabel("Bill number FO-1").fill("FRT-101");
  const post = page.getByRole("button", { name: "Settle FO-1" });
  await post.click();
  await expect(page.getByRole("alert")).toContainText("Carrier bill confirmation is unavailable");
  await page.reload();
  const order = page.getByRole("row").filter({ hasText: "FO-1" });
  await expect(order).toContainText("settled");
  await expect(post).toHaveCount(0);
  await order.getByRole("button", { name: "Retry bill FO-1" }).click();
  await expect(done(page)).toContainText("FO-1 settled (their FRT-101): INR 100.00");
  await expect(order).toContainText("₹33.34");
  expect(requests).toHaveLength(2);
  expect(requests[1]).toMatchObject({ id: requests[0].id, kind: "transport", action: "settle", posting_date: date,
    parameters: { order: "FO-1", billed: 100, bill: "FRT-101" } });
  const saved = await (await page.request.get(companyUrl)).json();
  expect(saved.meta.revision).toBe(2);
  expect(saved.dataset.freight_orders[0]).toMatchObject({ billed: 100, status: "settled", settled_on: date, bill: "FRT-101" });
  const { csrf } = await (await page.request.get("/api/auth/csrf")).json();
  const books = await page.request.post(`/api/accounting?period_end=${date}`, { data: saved.dataset, headers: { "X-CSRF-Token": csrf } });
  expect(books.ok(), await books.text()).toBe(true);
  const ledger = await books.json();
  expect(ledger.vouchers.filter((v: { number: string }) => v.number === "FO-1")).toHaveLength(1);
  expect(ledger.balances).toContainEqual(expect.objectContaining({ company: "E1", account: "PAYABLES", balance: -100 }));

  const creditDate = "2026-01-08";
  await order.getByText("Record carrier credit", { exact: true }).click();
  await page.getByLabel("Credit posting date FO-1").fill(creditDate);
  await page.getByLabel("Credit number FO-1").fill("CR-FRT-101");
  await page.getByLabel("Credit reason FO-1").fill("Fuel charge corrected");
  await page.getByRole("button", { name: "Credit FO-1", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Carrier credit confirmation is unavailable");
  await page.reload();
  await expect(order).toContainText("Credit CR-FRT-101");
  await order.getByRole("button", { name: "Retry credit FO-1" }).click();
  await expect(done(page)).toContainText("FO-1 credited (their CR-FRT-101): INR 100.00");
  expect(requests).toHaveLength(4);
  expect(requests[3]).toMatchObject({ id: requests[2].id, kind: "transport", action: "credit", posting_date: creditDate,
    parameters: { order: "FO-1", credit_of: "FO-1", bill: "CR-FRT-101", reason: "Fuel charge corrected" } });
  const credited = await (await page.request.get(companyUrl)).json();
  expect(credited.meta.revision).toBe(3);
  expect(credited.dataset.freight_orders[0]).toMatchObject({ status: "shipped", billed: null,
    bill_credits: [{ billed: 100, bill: "FRT-101", reference: "CR-FRT-101", settled_on: date, date: creditDate }] });

  const correctedDate = "2026-01-09";
  await page.getByLabel("Posting date FO-1").fill(correctedDate);
  await page.getByLabel("Billed FO-1").fill("80");
  await page.getByLabel("Bill number FO-1").fill("FRT-101");
  await post.click();
  await expect(done(page)).toContainText("FO-1 settled (their FRT-101): INR 80.00");
  const corrected = await (await page.request.get(companyUrl)).json();
  expect(corrected.meta.revision).toBe(4);
  expect(corrected.dataset.freight_orders[0].bill_credits).toHaveLength(1);
  const historical = await page.request.post(`/api/accounting?period_end=${date}`, {
    data: corrected.dataset, headers: { "X-CSRF-Token": csrf },
  });
  expect(historical.ok(), await historical.text()).toBe(true);
  expect(await historical.json()).toEqual(ledger);
  const correctedBooks = await page.request.post(`/api/accounting?period_end=${correctedDate}`, {
    data: corrected.dataset, headers: { "X-CSRF-Token": csrf },
  });
  expect(correctedBooks.ok(), await correctedBooks.text()).toBe(true);
  const journal = await correctedBooks.json();
  expect(journal.vouchers.map((v: { number: string }) => v.number).sort()).toEqual(["FO-1", "FO-1/B2", "FO-1/REV"]);
  expect(journal.balances).toContainEqual(expect.objectContaining({ company: "E1", account: "PAYABLES", balance: -80 }));

  await page.goto("/#/buying/owed");
  const carrierBills = page.getByRole("table", { name: "Carrier bills" });
  const rebill = carrierBills.getByRole("row").filter({ hasText: "FO-1/B2" });
  await expect(rebill).toContainText("to pay");
  await expect(carrierBills.getByText("CR-FRT-101")).toBeVisible();
  await rebill.getByText("Record payment", { exact: true }).click();
  const paymentDate = "2026-01-10";
  await rebill.getByLabel("Payment date FO-1/B2").fill(paymentDate);
  await rebill.getByLabel("Bank reference FO-1/B2").fill("WIRE-2026-001");
  await rebill.getByRole("button", { name: "Record payment FO-1/B2" }).click();
  await expect(rebill.getByRole("alert")).toContainText("Payment confirmation is unavailable");
  await page.reload();
  await expect(rebill).toContainText("paid");
  await rebill.getByRole("button", { name: "Retry carrier payment FO-1/B2" }).click();
  await expect(rebill.getByRole("status")).toContainText("INR 80.00 paid on FO-1/B2");
  expect(requests).toHaveLength(7);
  const payment = { kind: "transport", action: "pay_bill", posting_date: paymentDate,
    parameters: { order: "FO-1", voucher: "FO-1/B2", amount: 80, reference: "WIRE-2026-001" } };
  expect(requests[5]).toMatchObject(payment);
  expect(requests[6]).toMatchObject({ ...payment, id: requests[5].id });
  const cash = await (await page.request.get(companyUrl)).json();
  expect(cash.meta.revision).toBe(5);
  expect(cash.dataset.freight_orders[0].bill_payments).toEqual([expect.objectContaining({ date: paymentDate, amount: 80, reference: "WIRE-2026-001" })]);
  const paymentBooks = await page.request.post(`/api/accounting?period_end=${paymentDate}`, {
    data: cash.dataset, headers: { "X-CSRF-Token": csrf },
  });
  expect(paymentBooks.ok(), await paymentBooks.text()).toBe(true);
  const paidJournal = await paymentBooks.json();
  expect(paidJournal.vouchers.filter((v: { number: string }) => v.number === "FO-1/B2/P-1")).toHaveLength(1);
  expect(paidJournal.balances).toContainEqual(expect.objectContaining({ company: "E1", account: "PAYABLES", balance: 0 }));
  expect(paidJournal.balances).toContainEqual(expect.objectContaining({ company: "E1", account: "BANK", balance: -80 }));
});

test("Receiving and AP allocate freight, match its payment and recover the carrier refund", async ({ page }) => {
  test.setTimeout(90_000);
  const company = {
    settings: { company_name: "Carrier closeout fixture", planning_start: "2026-01-05", horizon_days: 28, currency: "INR" },
    execution: { price_control: "moving_average" },
    locations: [{ id: "W", type: "dc", entity: "E1" }, { id: "S", type: "supplier" }],
    products: [{ id: "X", type: "FG", weight_kg: 1 }], entities: [{ id: "E1" }],
    location_products: [{ location: "W", product: "X", on_hand: 0 }],
    purchasing_sources: [{ id: "PS", supplier: "S", location: "W", product: "X", price: 1, lead_time_days: 1 }],
    purchase_orders: [{ id: "PO-1", supplier: "S", location: "W", order_date: "2026-01-05", sent_on: "2026-01-05" }],
    receipts: [{ id: "PO-1-10", kind: "purchase", location: "W", product: "X", qty: 400, due_date: "2026-01-07",
      source: "PS", po: "PO-1", price: 1 }],
    purchase_valuation: [{ id: "PO-1-10", supplier: "S", location: "W", product: "X", currency: "INR", base: 1,
      duty: 0, freight: 0, handling: 0 }],
    movements: [{ id: "M-1", date: "2026-01-07", type: "receipt", location: "W", product: "X", qty: 400,
      reference: "PO-1-10", counterparty: "S" }],
    lanes: [{ id: "L", origin: "S", destination: "W", modes: [{ mode: "truck_ftl", transit_days: 1 }] }],
    carriers: [{ id: "CR", rates: [{ lane: "L", per_shipment: 900 }] }],
    freight_orders: [{ id: "FO-1", lane: "L", mode: "truck_ftl", carrier: "CR", ship_from: "S", ship_to: "W",
      planned_on: "2026-01-06", shipped_on: "2026-01-06", status: "settled", planned_cost: 900, billed: 950,
      bill: "FRT-950", settled_on: "2026-01-08", purchases: ["PO-1-10"] }],
  };
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "inbound-freight.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`freight-closeout-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Freight AP");
  await page.getByLabel(/^Password/).fill("fixture-only-spring-clover");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  await page.goto("/#/buying/owed");
  const row = page.getByRole("table", { name: "Carrier bills" }).getByRole("row").filter({ hasText: "FO-1" });
  const choice = row.getByLabel("Carrier event FO-1", { exact: true });
  const eventDate = row.getByLabel("Carrier event date FO-1");
  const target = row.getByLabel("Carrier event target FO-1");
  const reference = row.getByLabel("Carrier event reference FO-1");
  const amount = row.getByLabel("Carrier event amount FO-1");
  await row.getByText("Carrier bill actions").click();
  await choice.selectOption("landed_cost");
  await eventDate.fill("2026-01-09");
  await target.selectOption("M-1");
  await reference.fill("SERVICE-950");
  await amount.fill("950");
  await row.getByRole("button", { name: "Allocate landed cost" }).click();
  await expect(row.getByRole("status")).toContainText("Landed cost recorded on FO-1");

  await row.getByText("Record payment", { exact: true }).click();
  await row.getByLabel("Payment date FO-1").fill("2026-01-10");
  await row.getByLabel("Bank reference FO-1").fill("WIRE-950");
  await row.getByRole("button", { name: "Record payment FO-1" }).click();
  await expect(row.getByText("Unmatched bank movements (1)")).toBeVisible();
  await choice.selectOption("match_bank");
  await eventDate.fill("2026-01-11");
  await target.selectOption("FO-1/P-1");
  await reference.fill("WIRE-950");
  await amount.fill("-950");
  await row.getByLabel("Statement account FO-1").fill("OPERATING");
  await row.getByLabel("Statement line FO-1").fill("JAN/L50");
  await row.getByRole("button", { name: "Match bank statement" }).click();
  await expect(row.getByText("Unmatched bank movements (1)")).toHaveCount(0);

  await choice.selectOption("reverse_landed");
  await target.selectOption("1");
  await eventDate.fill("2026-01-12");
  await row.getByRole("button", { name: "Reverse landed cost" }).click();
  await expect(row.getByText("Landed-cost reversal recorded on FO-1.")).toBeVisible();
  await choice.selectOption("adjust_bill");
  await eventDate.fill("2026-01-13");
  await reference.fill("CR-100");
  await amount.fill("100");
  await row.getByLabel("Carrier credit reason FO-1").fill("Disputed rate");
  await row.getByRole("button", { name: "Post carrier credit" }).click();
  await expect(row).toContainText("refund due");

  let companyUrl = "";
  const attempts: { id: string; parameters: { event?: { kind: string } } }[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const payload = route.request().postDataJSON();
    if (payload.parameters.event?.kind === "refund_bill") {
      attempts.push(payload);
      if (attempts.length === 1) {
        companyUrl = route.request().url().replace(/\/commands$/, "");
        const committed = await route.fetch();
        expect(committed.ok(), await committed.text()).toBe(true);
        return route.abort("failed");
      }
    }
    await route.continue();
  });
  await choice.selectOption("refund_bill");
  await eventDate.fill("2026-01-14");
  await reference.fill("WIRE-BACK-100");
  await row.getByRole("button", { name: "Record carrier refund" }).click();
  await expect(row.getByRole("alert")).toContainText("Carrier event confirmation is unavailable");
  await page.reload();
  await expect(row).toContainText("refunded");
  await row.getByRole("button", { name: "Retry carrier event FO-1" }).click();
  await expect(row.getByText("Carrier refund recorded on FO-1.")).toBeVisible();
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toMatchObject({ id: attempts[0].id, parameters: attempts[0].parameters });
  const final = await (await page.request.get(companyUrl)).json();
  expect(final.dataset.freight_orders[0].bill_events.filter((entry: { kind: string }) => entry.kind === "refund_bill")).toHaveLength(1);
});

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
