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

test("a live physical count retains unsaved edits and can confirm one posted difference after reload", async ({ page }) => {
  const date = "2026-01-04";
  const company = {
    settings: { company_name: "Count fixture", planning_start: "2026-01-05", horizon_days: 28, default_calendar: "CAL" },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "P", type: "plant" }],
    products: [{ id: "A", type: "FG", price: 10 }],
    location_products: [{ location: "P", product: "A", on_hand: 100 }],
    movements: [{ id: "GM-00001", type: "opening", date, location: "P", product: "A", qty: 100 }],
    inventory_docs: [{ id: "PI-00001", date, block: true,
      items: [{ location: "P", product: "A", book_qty: 100, counted: 98 }] }],
  };
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "count.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`count-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Warehouse counter");
  await page.getByLabel(/^Password/).fill("fixture-only-autumn-rowan");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  await page.goto("/#/execution/count");

  let rejectedEntry = false;
  let companyUrl = "";
  await page.route("**/api/companies/*/commands", async (route) => {
    const request = route.request().postDataJSON();
    if (request.action === "count_enter" && !rejectedEntry) {
      rejectedEntry = true;
      return route.fulfill({ status: 503, json: { detail: "Fixture count save unavailable" } });
    }
    if (request.action === "count_post") {
      companyUrl = route.request().url().replace(/\/commands$/, "");
      expect(request.posting_date).toBe(date);
      expect(request.parameters.counts[0].qty).toBe(94);
      const committed = await route.fetch();
      expect(committed.ok(), await committed.text()).toBe(true);
      return route.abort("failed");
    }
    await route.continue();
  });
  const counted = page.getByLabel(/^Counted A\s*$/);
  const post = page.getByRole("button", { name: "Post differences" });
  await expect(counted).toHaveValue("98");
  await counted.fill("94");
  await expect(post).toBeDisabled();
  const entry = page.getByRole("button", { name: "Save 1 count", exact: true });
  await entry.click();
  await expect(page.getByRole("alert")).toContainText("Fixture count save unavailable");
  await expect(counted).toHaveValue("94");
  await expect(post).toBeDisabled();
  await entry.click();
  await expect(post).toBeEnabled();
  await post.click();
  await expect(page.getByRole("alert")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Check posting PI-00001" }).click();
  await expect(page.getByRole("status").filter({ hasText: "PI-00001 posted" })).toContainText("1 difference (+0, −6)");
  const saved = await (await page.request.get(companyUrl)).json();
  expect(saved.meta.revision).toBe(3);
  expect(saved.dataset.inventory_docs[0]).toMatchObject({ status: "posted", items: [{ counted: 94 }] });
  expect(saved.dataset.movements.filter((m: { type: string }) => m.type === "adjustment")).toMatchObject([{ qty: -6, date }]);
  expect(saved.dataset.location_products[0].on_hand).toBe(94);
});

test("a different reviewer can post a saved above-limit stock count", async ({ page, request }) => {
  const stamp = Date.now();
  const ownerEmail = `reviewer-${stamp}@example.invalid`;
  const counterEmail = `counter-${stamp}@example.invalid`;
  const password = "fixture-only-autumn-rowan";
  const date = "2026-01-04";
  const signup = async (email: string) => {
    const response = await request.post("/api/auth/signup", { data: { email, password, name: email.split("@")[0] } });
    expect(response.ok(), await response.text()).toBe(true);
    return { Authorization: `Bearer ${(await response.json()).token}` };
  };
  const owner = await signup(ownerEmail);
  const counter = await signup(counterEmail);
  const company = await request.post("/api/companies", { headers: owner, data: { dataset: {
    settings: { company_name: "Count review fixture", currency: "KWD", planning_start: "2026-01-05",
      horizon_days: 28, default_calendar: "CAL" },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "P", type: "plant" }],
    products: [{ id: "A", type: "FG", standard_cost: 1.234 }],
    location_products: [{ location: "P", product: "A", on_hand: 100 }],
    movements: [{ id: "GM-00001", type: "opening", date, location: "P", product: "A", qty: 100,
      standard_price: 1.234, opening_standards: { P: { A: 1.234 } } }],
    finance: { inventory_count_limits: { item_minor: 1000, document_minor: 1000, reviewers: [ownerEmail] },
      control_roles: { warehouse: [ownerEmail, counterEmail], inventory_adjustment: [ownerEmail, counterEmail] } },
    inventory_docs: [{ id: "PI-00001", date, items: [{ location: "P", product: "A", book_qty: 100 }] }],
  } } });
  expect(company.ok(), await company.text()).toBe(true);
  const path = `/api/companies/${(await company.json()).id}`;
  const members = await request.post(`${path}/members`, { headers: owner, data: { email: counterEmail, role: "planner" } });
  expect(members.ok(), await members.text()).toBe(true);
  const rows = await members.json() as { email: string; invite_link?: string }[];
  const token = rows.find((member) => member.email === counterEmail)?.invite_link?.split("/").at(-1);
  expect(token).toBeTruthy();
  const joined = await request.post("/api/auth/invites/accept", { headers: counter, data: { token } });
  expect(joined.ok(), await joined.text()).toBe(true);
  const count = await request.post(`${path}/commands`, { headers: counter, data: {
    id: "review-fixture-entry", base_revision: 1, kind: "stock", action: "count_enter", posting_date: date,
    parameters: { doc: "PI-00001", counts: [{ location: "P", product: "A", qty: 99 }] },
  } });
  expect(count.ok(), await count.text()).toBe(true);

  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Sign in", exact: true }).click();
  await page.getByLabel("E-mail").fill(ownerEmail);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByRole("button", { name: /Open Count review fixture/ }).click();
  await expect(page).toHaveURL(/#\/home$/);
  await page.goto("/#/execution/count");
  await page.getByRole("button", { name: "Post differences", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("KWD 1.234 exceeds inventory posting limits");
  await page.getByLabel("Reason for above-limit posting").fill("Independently confirmed at the warehouse");
  await page.getByRole("button", { name: "Review and post above limit" }).click();
  await expect(page.getByRole("status").filter({ hasText: "PI-00001 posted" })).toContainText("1 difference");
  const stored = await request.get(path, { headers: owner });
  expect(stored.ok(), await stored.text()).toBe(true);
  const saved = await stored.json();
  expect(saved.meta.revision).toBe(3);
  expect(saved.dataset.movements.filter((m: { type: string }) => m.type === "adjustment")).toMatchObject([{ qty: -1, date }]);
});

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

test("count-date book starts from the intervening receipt and creates no adjustment", async ({ page }) => {
  const company = {
    settings: { company_name: "Count-date inventory", planning_start: "2026-01-08", horizon_days: 28, default_calendar: "CAL" },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "P", type: "plant" }],
    products: [{ id: "A", type: "FG" }],
    location_products: [{ location: "P", product: "A", on_hand: 30 }],
    movements: [
      { id: "GM-00001", type: "opening", date: "2026-01-02", location: "P", product: "A", qty: 20 },
      { id: "GM-00002", type: "receipt", date: "2026-01-06", location: "P", product: "A", qty: 10 },
    ],
  };
  await page.goto("/");
  const file = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await file).setFiles({ name: "count-date.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page).toHaveURL(/#\/home$/);
  await page.goto("/#/execution/count");
  await page.getByLabel("Place to count").selectOption("P");
  await page.getByLabel("Count date", { exact: true }).fill("2026-01-05");
  await page.getByLabel("Book quantity", { exact: true }).selectOption("at_count");
  await page.getByLabel(/Hold postings/).uncheck();
  await page.getByRole("button", { name: "Start counting 1 product" }).click();
  await page.getByLabel("Actual count date").fill("2026-01-07");
  await page.getByRole("button", { name: "Record book stock" }).click();
  await page.getByLabel("Show the book stock").check();
  await expect(page.getByRole("row", { name: /^A no batch/ })).toContainText("30");
  await page.getByLabel(/^Counted A\s*$/).fill("30");
  await page.getByRole("button", { name: "Save 1 count", exact: true }).click();
  await page.getByRole("button", { name: "Post differences" }).click();
  await expect(page.getByRole("status").filter({ hasText: "PI-00001 posted" })).toContainText("the counts match the book");
});
