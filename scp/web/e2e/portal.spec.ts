import { expect, test, type Page } from "@playwright/test";

// Enterprise 7.2, used the guide's way on Kaveri. Input: 2,000 kg of enamelled copper wire ordered from Hindalco
// copper (Silvassa), wanted Mon 12 Oct, at 890 a kg (the scale from 2,000 kg); a link to the supplier portal for them.
// Processing: the supplier, in a browser of their own with no account, confirms 1,200 for Fri 9 Oct and 800 for
// Fri 16 Oct, then sends dispatch advice for 1,200 shipped Sat 10 Oct, which on the 2-day lane arrive Mon 12 Oct;
// their system sends a UBL DespatchAdvice for the other 800. Output: the company on the server has their
// confirmation and two shipping notices as the link maker's changes, the plan counts on the arrival dates, and the
// goods are received against the notice in one step. Engine: scp/portal.

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/status of (401|409|422)/.test(m.text())) errors.push(m.text()); });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

async function ownerOnServer(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`portal-${Date.now()}@kaveri.in`);
  await page.getByLabel("Your name").fill("Asha Buyer");
  await page.getByLabel(/^Password/).fill("kaveri-2026-pumps");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
}

const done = (page: Page) => page.locator('.banner[role="status"]').last();

const despatch = (po: string, line: string) => `<?xml version="1.0" encoding="UTF-8"?>
<DespatchAdvice xmlns="urn:oasis:names:specification:ubl:schema:xsd:DespatchAdvice-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:ID>SC/DA/9044</cbc:ID><cbc:IssueDate>2026-10-14</cbc:IssueDate>
  <cac:OrderReference><cbc:ID>${po}</cbc:ID></cac:OrderReference>
  <cac:Shipment><cbc:ID>1</cbc:ID><cac:Delivery>
    <cac:Despatch><cbc:ActualDespatchDate>2026-10-14</cbc:ActualDespatchDate></cac:Despatch>
  </cac:Delivery></cac:Shipment>
  <cac:DespatchLine><cbc:ID>1</cbc:ID><cbc:DeliveredQuantity unitCode="KGM">800</cbc:DeliveredQuantity>
    <cac:OrderLineReference><cbc:LineID>${line}</cbc:LineID></cac:OrderLineReference>
  </cac:DespatchLine>
</DespatchAdvice>`;

test("a supplier confirms and dispatches on their link; the company plans with it and receives against it", async ({ page, browser }) => {
  test.setTimeout(300_000);
  await ownerOnServer(page);

  // input: the copper order, released and sent
  await page.goto("/#/buying/orders");
  await page.getByRole("button", { name: "New purchase order" }).click();
  await page.getByLabel("What to buy").selectOption("PIR-CU");
  await page.getByLabel("Quantity to buy").fill("2000");
  await page.getByLabel("Wanted on").fill("2026-10-12");
  await page.getByRole("button", { name: "Create the purchase order" }).click();
  const made = page.getByRole("status").filter({ hasText: /PO-\d+ created/ });
  await expect(made).toBeVisible({ timeout: 30_000 });
  const po = (await made.textContent())!.match(/PO-\d+/)![0];
  const line = `${po}-10`;
  for (let i = 0; i < 4; i++) {
    const release = page.getByRole("button", { name: /^(Release: .*|Approve)$/ });
    if (!(await release.isVisible())) break;
    await release.click();
    await expect(page.locator(".banner.ok").last()).toBeVisible();
  }
  await page.getByRole("button", { name: "Mark as sent" }).click();
  await expect(page.locator(".banner.ok").last()).toContainText("sent to Hindalco copper (Silvassa)");
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/, { timeout: 30_000 });

  // the link, for Hindalco copper only
  await page.getByRole("tab", { name: /Supplier portal/ }).click();
  await page.getByLabel("Supplier", { exact: true }).selectOption("SUP-COPPER");
  const theirs = page.getByRole("table", { name: "What the supplier sees" });
  await expect(theirs.getByRole("row", { name: new RegExp(line) })).toContainText("to confirm");
  await expect(theirs.getByRole("row", { name: new RegExp(line) })).toContainText("₹890.00");    // 2,000 kg: the scale price
  await page.getByRole("button", { name: "Make a link" }).click();
  const shown = page.getByLabel("The new link");
  await expect(shown).toHaveValue(/#\/portal\/scp_sp_/);
  const link = await shown.inputValue();
  await expect(page.getByRole("table", { name: "Links" })).toContainText("not yet");

  // processing: the supplier, in a browser of their own, no account
  const them = await (await browser.newContext()).newPage();
  await them.goto(link);
  await expect(them.getByRole("heading", { name: /Orders from Kaveri Kitchenware/ })).toBeVisible();
  await expect(them.locator(".portal-head")).toContainText("For Hindalco copper (Silvassa)");
  const mine = them.getByRole("table", { name: "Your order lines" });
  await expect(mine.getByRole("row")).toHaveCount(2);                               // the header and their one line
  const row = mine.getByRole("row", { name: new RegExp(line) });
  await expect(row).toContainText("2,000 kg");
  await expect(row).toContainText("to confirm");
  // 1,200 a week early on Fri 9 Oct, the other 800 on Fri 16 Oct
  await row.getByLabel(`Quantity ${line}`, { exact: true }).fill("1200");
  await row.getByLabel(`Date ${line}`, { exact: true }).fill("2026-10-09");
  await row.locator("summary", { hasText: "in two deliveries" }).click();
  await row.getByLabel(`Second quantity ${line}`).fill("800");
  await row.getByLabel(`Second date ${line}`).fill("2026-10-16");
  await them.getByLabel("Your confirmation number").fill("SC/OC/3381");
  await row.getByRole("button", { name: `Confirm ${line}` }).click();
  await expect(them.locator('.banner[role="status"]')).toContainText(`${po} confirmed`, { timeout: 30_000 });
  await expect(row).toContainText("changed");
  await expect(row).toContainText("1,200 on Fri 9 Oct");
  await expect(row).toContainText("800 on Fri 16 Oct");
  // the lorry leaves Sat 10 Oct with 1,200 kg in batch CU-7781: on the 2-day lane it arrives Mon 12 Oct
  const lorry = them.getByRole("table", { name: "What is on the lorry" });
  await lorry.getByLabel(`Shipped quantity ${line}`).fill("1200");
  await lorry.getByLabel(`Batch ${line}`).fill("CU-7781");
  await them.getByLabel("Shipped on").fill("2026-10-10");
  await them.getByLabel("Lorry receipt or dispatch note").fill("LR 40417");
  await them.getByRole("button", { name: "Send dispatch advice" }).click();
  await expect(them.locator('.banner[role="status"]')).toContainText(
    `ASN-00001: Hindalco copper (Silvassa) dispatched 1,200 Enamelled copper wire (${line}) on Sat 10 Oct (their LR 40417), arriving Mon 12 Oct.`,
    { timeout: 30_000 });
  await expect(them.getByRole("table", { name: "Your dispatch advice" })).toContainText("on the way");
  await expect(row).toContainText("1,200 on Mon 12 Oct");                           // the lorry's goods: the arrival
  await expect(row).toContainText("1,200 on the way");
  await them.screenshot({ path: "test-results/portal-supplier.png", fullPage: true });
  // a supplier on a phone: the page fits, the tables scroll inside themselves
  await them.setViewportSize({ width: 390, height: 844 });
  expect(await them.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  // a link to nothing opens nothing
  await them.goto(link.replace(/scp_sp_.*/, "scp_sp_made-up"));
  await expect(them.getByText("This link does not open anything")).toBeVisible();

  // output: the planner sees their saves, plans with them, and receives against the notice
  await expect(page.getByRole("button", { name: "Show their changes" })).toBeVisible({ timeout: 75_000 });
  await page.getByRole("button", { name: "Show their changes" }).click();
  await page.goto("/#/buying/portal");
  await page.getByLabel("Supplier", { exact: true }).selectOption("SUP-COPPER");
  const seen = page.getByRole("table", { name: "What the supplier sees" }).getByRole("row", { name: new RegExp(line) });
  await expect(seen).toContainText("1,200 on Mon 12 Oct", { timeout: 30_000 });
  await expect(seen).toContainText("800 on Fri 16 Oct");
  const notices = page.getByRole("table", { name: "Shipping notices" });
  await expect(notices.getByRole("row", { name: /ASN-00001/ })).toContainText("their LR 40417");
  await expect(page.getByRole("table", { name: "Links" })).toContainText("2 times");
  // their system's DespatchAdvice for the other 800, which came by mail: no arrival date, so the lane's 2 days
  await page.getByLabel("UBL message").fill(despatch(po, line));
  await page.getByRole("button", { name: "Read the message" }).click();
  await expect(done(page)).toContainText(`ASN-00002: Hindalco copper (Silvassa) dispatched 800 Enamelled copper wire (${line}) on Wed 14 Oct (their SC/DA/9044), arriving Fri 16 Oct.`,
    { timeout: 30_000 });
  // the goods of the first lorry come on Mon 12 Oct: received on the order with their batch
  await page.getByLabel("Received on").fill("2026-10-12");
  await notices.getByRole("button", { name: "Receive ASN-00001" }).click();
  await expect(done(page)).toContainText("ASN-00001 received", { timeout: 30_000 });
  await expect(notices.getByRole("row", { name: /ASN-00001/ })).toContainText("received");
  await expect(seen.locator("td").nth(6)).toHaveText("800");                          // the second lorry's, still on the way
  await page.screenshot({ path: "test-results/portal-buying.png", fullPage: true });
  await page.goto("/#/history");
  await expect(page.locator("main")).toContainText("dispatch advice from Hindalco copper (Silvassa) on the supplier portal (link L");

  // the link withdrawn: the supplier's page opens nothing any more
  await page.goto("/#/buying/portal");
  await page.getByLabel("Supplier", { exact: true }).selectOption("SUP-COPPER");
  await page.getByRole("button", { name: /^Withdraw L\d+$/ }).click();
  await expect(page.getByRole("table", { name: "Links" })).toContainText("withdrawn");
  await them.goto(link);
  await expect(them.getByText("This link does not open anything")).toBeVisible();
});
