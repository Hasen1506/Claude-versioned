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
  await page.getByLabel("Tally ledger for Bank").fill("HDFC Bank 50200");
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
