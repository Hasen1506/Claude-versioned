import { expect, test, type Page } from "@playwright/test";

// N139, N143: on a server that sends mail (the second server of playwright.config.ts, whose mail server is
// e2e/smtp_sink.py), firming e-mails the purchase order to its supplier, Send from here sends it again from Buying, an
// address the company does not know is refused, and Connections lists what went.
test.use({ baseURL: "http://127.0.0.1:8766" });
const SINK = "http://127.0.0.1:2526/messages";
type Taken = { from: string; to: string[]; subject: string; reply_to: string; text: string; attachments: string[]; pdf: string[] };

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/status of (422|409)/.test(m.text())) errors.push(m.text()); });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

function fixture(): Record<string, unknown> {
  return {
    settings: { company_name: "Mehta Paints", company_address: "Plot 4, MIDC\nPune", planning_start: "2026-01-05", horizon_days: 28,
      default_calendar: "CAL", wacc: 0, holding_spread: 0 },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "PUNE", name: "Pune plant", type: "plant" }, { id: "SHARMA", name: "Sharma Metals", type: "supplier", address: "Bhosari\nPune" }],
    products: [{ id: "TIN", name: "Tin of white", type: "FG", price: 100 }],
    location_products: [{ location: "PUNE", product: "TIN", on_hand: 0, lot_sizing: { policy: "L4L" } }],
    purchasing_sources: [{ id: "PIR-TIN", supplier: "SHARMA", location: "PUNE", product: "TIN", price: 10, lead_time_days: 3 }],
    vendors: [{ supplier: "SHARMA", email: "sales@sharma.example" }],
    demand: [{ id: "SO-1", location: "PUNE", product: "TIN", date: "2026-01-12", qty: 120, kind: "sales_order" }],
  };
}

async function onServer(page: Page, data = fixture()): Promise<string> {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "mail.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(data)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  const email = `buyer-${Date.now()}@mehta.example`;
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Your name").fill("Ravi Buyer");
  await page.getByLabel(/^Password/).fill("mehta-2026-plans");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  // the server mails documents only for someone whose address is confirmed (CV-H07): confirm it by its mailed link
  await page.request.delete(SINK);
  await page.getByRole("button", { name: "Confirm my address" }).click();
  await expect.poll(async () => (await taken(page)).length, { timeout: 15_000 }).toBe(1);
  const link = (await taken(page))[0].text.match(/https?:\/\/\S+#\/account\/verify\/\S+/)![0];
  await page.goto(link);
  await expect(page.getByText(/is confirmed as yours/)).toBeVisible();
  await page.request.delete(SINK);
  return email;
}

const done = (page: Page) => page.locator('.banner[role="status"]').last();
const taken = async (page: Page): Promise<Taken[]> => (await page.request.get(SINK)).json();

test("mail from the server: firming e-mails the purchase order, Send from here sends it again, unknown addresses are refused", async ({ page }) => {
  test.setTimeout(180_000);
  await page.request.delete(SINK);
  const email = await onServer(page);

  // firming: the button says the orders go by e-mail, and the supplier's mail server has the order attached
  await page.goto("/#/execution/orders");
  // the plan may still be calculating on its own: wait for the order to firm, else ask for the plan
  const calculate = page.getByRole("button", { name: /^(Recalculate the supply plan|Calculate the supply plan)$/ });
  const firm = page.getByRole("button", { name: "Make 1 order firm", exact: true });
  await expect(firm.or(calculate).first()).toBeVisible({ timeout: 45_000 });
  if (!(await firm.isVisible())) await calculate.click({ timeout: 5_000 }).catch(() => undefined);
  await firm.click({ timeout: 45_000 });
  await expect(done(page)).toContainText(/1 planned order firmed.*PO-00001/, { timeout: 45_000 });
  await page.getByRole("button", { name: "E-mail the 1 purchase order to the suppliers" }).click();
  await expect(done(page)).toContainText("E-mailed PO-00001 to sales@sharma.example.", { timeout: 45_000 });
  await expect(done(page)).toContainText("1 order sent: PO-00001.");
  await expect.poll(async () => (await taken(page)).length).toBe(1);
  const [first] = await taken(page);
  expect(first.from).toBe("plan@scp.example");
  expect(first.to).toEqual(["sales@sharma.example"]);
  expect(first.subject).toContain("PO-00001");
  expect(first.reply_to).toContain(email);
  expect(first.attachments).toEqual(["PO-00001.pdf", "PO-00001.html"]);
  expect(first.pdf).toEqual(["%PDF-1.4"]);

  // Send from here on Buying: to the supplier's address, filled in
  await page.goto("/#/buying/orders/PO-00001");
  await page.getByRole("button", { name: "Send from here" }).click();
  await expect(page.getByLabel("Send to")).toHaveValue("sales@sharma.example");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByText("Sent to sales@sharma.example")).toBeVisible({ timeout: 45_000 });
  await expect.poll(async () => (await taken(page)).length).toBe(2);

  // an address the company does not know is not sent to
  await page.reload();
  await page.getByRole("button", { name: "Send from here" }).click();
  await page.getByLabel("Send to").fill("someone@elsewhere.example");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("someone@elsewhere.example is not an address of this company's suppliers");
  expect((await taken(page)).length).toBe(2);

  // Connections lists both, sent, with the order attached
  await page.goto("/#/connections/mail");
  await expect(page.locator("main")).toContainText("The server sends mail from plan@scp.example");
  const rows = page.locator("tr", { hasText: "PO-00001" });
  await expect(rows).toHaveCount(2);
  await expect(rows.first()).toContainText("attached: PO-00001.pdf, PO-00001.html");
  await expect(rows.first()).toContainText("sales@sharma.example");
});

test("payment reminders and statements (N124): an overdue invoice falls due a reminder, sent from here and recorded", async ({ page }) => {
  test.setTimeout(180_000);
  await page.request.delete(SINK);
  const data = fixture();
  (data.locations as object[]).push({ id: "KUMAR", name: "Kumar Stores", type: "customer", address: "MG Road\nPune" });
  data.customers = [{ customer: "KUMAR", contact: "Mr Kumar", email: "accounts@kumar.example" }];
  data.sales = { reminder_days: [7, 21, 35] };
  data.invoices = [
    { id: "INV-00001", customer: "KUMAR", date: "2025-11-20", due_date: "2025-12-20", lines: [{ product: "TIN", qty: 10, price: 100 }] },
    { id: "INV-00002", customer: "KUMAR", date: "2026-01-02", due_date: "2026-02-01", lines: [{ product: "TIN", qty: 5, price: 100 }] },
  ];
  await onServer(page, data);

  // INV-00001 is 16 days overdue on the planning start: the first reminder is due; INV-00002 is not due yet
  await page.goto("/#/selling/customers");
  const owe = page.getByText("What customers owe");
  await owe.waitFor({ timeout: 15_000 }).catch(() => page.getByRole("button", { name: /^(Recalculate|Calculate)/ }).first().click());
  await expect(owe).toBeVisible({ timeout: 45_000 });
  const due = page.locator(".panel", { hasText: "Payment reminders due" });
  await expect(due).toContainText("Kumar Stores", { timeout: 45_000 });
  await expect(due).toContainText("INV-00001 (16 d)");
  await expect(due).not.toContainText("INV-00002");
  await due.getByRole("button", { name: "Send from here" }).click();
  await expect(due.getByLabel("Send to")).toHaveValue("accounts@kumar.example");
  await due.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Payment reminder 1 to Kumar Stores" })).toBeVisible({ timeout: 45_000 });
  await expect.poll(async () => (await taken(page)).length).toBe(1);
  const [m] = await taken(page);
  expect(m.to).toEqual(["accounts@kumar.example"]);
  expect(m.subject).toBe("Payment reminder from Mehta Paints");
  expect(m.text).toContain("Invoice INV-00001");
  expect(m.text).not.toContain("INV-00002");
  expect(m.attachments).toEqual(["KUMAR-reminder-1.pdf", "KUMAR-reminder-1.html"]);
  // recorded: nothing more is due, the invoice shows it
  await expect(page.locator(".panel", { hasText: "Payment reminders due" })).toHaveCount(0);
  await page.goto("/#/selling/bill");
  await expect(page.locator("tr", { hasText: "INV-00001" })).toContainText("reminder 1 sent");

  // the statement of account lists both, by age
  await page.goto("/#/selling/customers/KUMAR");
  const st = page.locator(".panel", { hasText: /^Statement of account: Kumar Stores/ });
  await expect(st).toContainText("Owed");
  await expect(st).toContainText("1–30 days");
  await st.getByRole("button", { name: "Send from here" }).click();
  await st.getByRole("button", { name: "Send", exact: true }).click();
  await expect(st.getByText("Sent to accounts@kumar.example")).toBeVisible({ timeout: 45_000 });
  await expect.poll(async () => (await taken(page)).length).toBe(2);
  const statement = (await taken(page))[1];
  expect(statement.subject).toBe("Statement of account from Mehta Paints");
  expect(statement.text).toContain("INV-00001");
  expect(statement.text).toContain("INV-00002");
});
