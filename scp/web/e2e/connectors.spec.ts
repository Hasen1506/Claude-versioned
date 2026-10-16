import { createServer, type Server } from "node:http";
import { expect, test, type Page } from "@playwright/test";

// ENTERPRISE_PLAN 3.2, on the second server of playwright.config.ts (which may reach "localhost", as a company's own
// Tally is allowed by name): Tally Prime asked on its port for its closing stock, tried first and taken; a purchase
// order released here made in Tally as a voucher and kept as taken; Zoho's credentials kept and never shown again.
test.use({ baseURL: "http://127.0.0.1:8766" });

const ITEMS = '<ENVELOPE><HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER><BODY><DATA><COLLECTION>' +
  '<STOCKITEM NAME="Tin White 1L"><PARENT>Tins</PARENT><BASEUNITS>Nos</BASEUNITS><CLOSINGBALANCE> 96 Nos</CLOSINGBALANCE></STOCKITEM>' +
  '<STOCKITEM NAME="Lid"><BASEUNITS>Nos</BASEUNITS><CLOSINGBALANCE>40 Nos</CLOSINGBALANCE></STOCKITEM>' +
  "</COLLECTION></DATA></BODY></ENVELOPE>";
const TAKEN = "<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS><CANCELLED>0</CANCELLED></RESPONSE>";

let tally: Server;
let port = 0;
const asked: string[] = [];

test.beforeAll(async () => {
  tally = createServer((req, res) => {
    let body = "";
    req.on("data", (c) => { body += c; });
    req.on("end", () => {
      asked.push(body);
      res.setHeader("Content-Type", "text/xml");
      if (body.includes("<TALLYREQUEST>Import Data</TALLYREQUEST>")) return res.end(TAKEN);
      if (body.includes("<ID>SCPItems</ID>")) return res.end(ITEMS);
      res.end("<ENVELOPE><BODY><DATA><COLLECTION></COLLECTION></DATA></BODY></ENVELOPE>");
    });
  });
  await new Promise<void>((resolve) => tally.listen(0, "localhost", () => resolve()));
  port = (tally.address() as { port: number }).port;
});

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/status of (422|409)/.test(m.text())) errors.push(m.text()); });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

test.afterAll(async () => { await new Promise((resolve) => tally.close(resolve)); });

function fixture(): Record<string, unknown> {
  return {
    settings: { company_name: "Mehta Paints", planning_start: "2026-01-05", horizon_days: 28, default_calendar: "CAL", wacc: 0, holding_spread: 0 },
    calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4, 5, 6] }],
    locations: [{ id: "PUNE", name: "Pune plant", type: "plant" }, { id: "SHARMA", name: "Sharma Metals", type: "supplier" }],
    products: [{ id: "TIN", name: "Tin of white", type: "FG", price: 100 }],
    location_products: [{ location: "PUNE", product: "TIN", on_hand: 0, lot_sizing: { policy: "L4L" } }],
    purchasing_sources: [{ id: "PIR-TIN", supplier: "SHARMA", location: "PUNE", product: "TIN", price: 10, lead_time_days: 3 }],
    purchase_orders: [{ id: "PO-00001", supplier: "SHARMA", location: "PUNE", order_date: "2026-01-02" }],
    receipts: [{ id: "PO-00001-10", kind: "purchase", location: "PUNE", product: "TIN", qty: 100, due_date: "2026-01-08",
      source: "PIR-TIN", po: "PO-00001", price: 10 }],
  };
}

async function owner(page: Page): Promise<void> {
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "mehta.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(fixture())) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`owner-${Date.now()}@mehta.example`);
  await page.getByLabel("Your name").fill("Asha Owner");
  await page.getByLabel(/^Password/).fill("mehta-2026-plans");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
}

test("Tally's stock tried and taken, a purchase order made in Tally, Zoho's credentials kept unseen", async ({ page }) => {
  await owner(page);
  await page.goto("/#/connections/imports");

  // Input: Tally's closing stock. Processing: its item name translated to the product here, counted at the plant.
  await page.getByRole("button", { name: "Connect Tally" }).click();
  await expect(page.getByLabel("Read from")).toHaveValue("tally");
  await expect(page.getByLabel("Import name")).toHaveValue("Tally stock");
  await page.getByLabel("Source").fill(`http://localhost:${port}`);
  const settings = page.getByRole("group", { name: "Tally Prime settings" });
  await settings.getByLabel("Company in Tally").fill("Mehta Paints");
  await settings.getByLabel("Stock is at").selectOption("PUNE");
  await page.getByRole("checkbox", { name: "Translate codes" }).check();
  await page.getByLabel("product codes").fill("Tin White 1L=TIN");
  await page.getByText("Try it first").click();
  await page.getByRole("button", { name: "Try it", exact: true }).click();
  // Output: what would be taken and refused, nothing saved yet
  const tried = page.getByLabel("Dry run");
  await expect(tried).toContainText("Dry run, nothing saved: 2 stock: 1 taken, 1 refused");
  await expect(tried).toContainText("PUNE / Lid");
  await expect(tried.getByRole("table", { name: "First rows as the fields here" })).toContainText("96");
  expect(asked.at(-1)).toContain("<SVCURRENTCOMPANY>Mehta Paints</SVCURRENTCOMPANY>");
  await page.getByRole("form", { name: "Scheduled import" }).screenshot({ path: "test-results/connectors-tally-form.png" });
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("status").first()).toContainText("Tally stock saved: it runs every hour at :05.");
  await expect(page.locator("main")).toContainText(`stock · from Tally Prime at http://localhost:${port}`);
  await page.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByRole("status").first()).toContainText("2 stock: 1 taken, 1 refused");

  // Input: PO-00001, released here. Processing: a purchase order voucher, Tally's ledger name translated.
  await page.getByRole("button", { name: "Connect Tally" }).click();
  await page.getByLabel("Import name").fill("Purchase orders to Tally");
  await page.getByLabel("What it brings").selectOption("send:purchase_order");
  await page.getByLabel("Source").fill(`http://localhost:${port}`);
  await page.getByRole("checkbox", { name: "Translate codes" }).check();
  await page.getByLabel("supplier codes").fill("Sharma Metals Pvt Ltd=SHARMA");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("status").first()).toContainText("Purchase orders to Tally saved");
  const row = page.locator("tr", { hasText: "Purchase orders to Tally" });
  await row.getByRole("button", { name: "Dry run" }).click();
  await expect(page.getByLabel("Dry run of Purchase orders to Tally")).toContainText("would be made in Tally (Sharma Metals Pvt Ltd)");
  expect(asked.some((a) => a.includes("Import Data"))).toBe(false);
  await row.getByRole("button", { name: "Run now" }).click();
  // Output: made in Tally, kept as taken; the next run has nothing to send
  await expect(page.getByRole("status").first()).toContainText("1 purchase order to Tally: 1 sent");
  const voucher = asked.find((a) => a.includes("Import Data"))!;
  expect(voucher).toContain("<VOUCHERNUMBER>PO-00001</VOUCHERNUMBER>");
  expect(voucher).toContain("<PARTYLEDGERNAME>Sharma Metals Pvt Ltd</PARTYLEDGERNAME>");
  await row.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByRole("status").first()).toContainText("nothing to send: every purchase order is in Tally as it is here");
  await page.getByRole("tab", { name: "Messages" }).click();
  const sent = page.locator("tr", { hasText: "purchase orders sent" }).first();
  await expect(sent).toContainText("1 purchase order to Tally: 1 sent");
  await sent.getByRole("button", { name: "1 line" }).click();
  await expect(page.locator("main")).toContainText("made in Tally as PO-00001");

  // Zoho: its self client's secrets are kept on the server and never shown again
  await page.getByRole("tab", { name: "Scheduled imports" }).click();
  await page.getByRole("button", { name: "Connect Zoho" }).click();
  await page.getByLabel("What it brings").selectOption("orders");
  await page.getByLabel("Import name").fill("Zoho orders");
  await page.getByLabel("Source").fill("60012345");
  const zoho = page.getByRole("group", { name: "Zoho Inventory settings" });
  await zoho.getByLabel("Client ID").fill("1000.TESTCLIENT");
  await zoho.getByLabel("Client secret").fill("test-secret-only");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("alert")).toContainText("Zoho needs the refresh token");
  await zoho.getByLabel("Refresh token").fill("1000.test-refresh-only");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("status").first()).toContainText("Zoho orders saved");
  await expect(page.locator("main")).toContainText("customer orders · from Zoho Inventory organisation 60012345");
  expect(await page.locator("main").innerText()).not.toContain("test-secret-only");
  await page.locator("tr", { hasText: "Zoho orders" }).getByRole("button", { name: "Change", exact: true }).click();
  await expect(zoho.getByLabel("Client secret")).toHaveValue("");
  await expect(zoho.getByLabel("Client secret")).toHaveAttribute("placeholder", "kept as it is");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await page.screenshot({ path: "test-results/connectors-zoho-phone.png", fullPage: true });
});
