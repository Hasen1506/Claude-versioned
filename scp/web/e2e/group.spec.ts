import { expect, test, type Page } from "@playwright/test";

// Enterprise 7.3, used the guide's way on Kaveri. Input: the Delhi DC belongs to Kaveri Appliances North, a company
// of the group in Haryana, which buys from Kaveri at cost plus 6 % (TP-NORTH). Processing: a planned transfer to Delhi
// is firmed (an inter-company order), shipped from Pune and received in Delhi; the shipment is on the billing due list
// and is billed on a tax invoice from Kaveri's series. Output: the invoice (place of supply Haryana) in three copies,
// each company's sale and purchase, the books of both and the group's, and a cancelled invoice back on the due list.
// Engine: scp/intercompany, scp/actuals/transfer_price.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const done = (page: Page) => page.locator('.banner[role="status"]').last();
const num = (t: string) => Number(t.replace(/[^\d.-]/g, ""));

test("an inter-company transfer: firmed, shipped, received, billed at the transfer price, and the group's books", async ({ page }) => {
  test.setTimeout(240_000);
  await openKaveri(page);

  // input: the company of the group and its transfer price, as set up
  await page.goto("/#/group");
  await expect(page.getByRole("heading", { name: "Group companies" })).toBeVisible();
  const cos = page.getByRole("table", { name: "Companies of the group" });
  await expect(cos.getByRole("row", { name: /Kaveri Appliances North/ })).toContainText("06AAJCK7716N1Z8", { timeout: 30_000 });
  await expect(cos.getByRole("row", { name: /Kaveri Appliances North/ })).toContainText("Delhi NCR DC");
  // STO-2201 was on the road at go-live: in North's books at the transfer price, not billed here
  await expect(page.getByText(/STO-2201 came from another company with no shipment in the journal/)).toBeVisible();

  // processing: firm a planned transfer to Delhi, ship it and receive it
  await page.goto("/#/plan/firm");
  await expect(page.getByRole("heading", { name: /^Firm zone:/ })).toBeVisible({ timeout: 45_000 });
  await page.getByRole("button", { name: "Select none" }).click();
  await page.locator("tr.clickable", { hasText: "stock transfer" }).filter({ hasText: "Delhi" }).first().locator("input").check();
  await page.getByRole("button", { name: "Make 1 order firm" }).click();
  await expect(page.getByText(/1 planned order firmed/)).toBeVisible();
  await page.goto("/#/execution/orders");
  const sto = (await page.locator("td b", { hasText: /^STO-\d{5}$/ }).first().innerText()).trim();

  await page.goto("/#/group/orders");
  const order = page.getByRole("table", { name: "Inter-company orders" }).getByRole("row", { name: new RegExp(sto) });
  await expect(order).toContainText("Kaveri Kitchenware Pvt Ltd (fictional) → Kaveri Appliances North Pvt Ltd (fictional)", { timeout: 30_000 });
  await expect(order).toContainText("cost plus 6.0% (TP-NORTH)");

  await page.goto("/#/execution/orders");
  const posted = page.locator(".banner.info", { hasText: "Posted" });
  await page.getByRole("button", { name: `Ship ${sto}`, exact: true }).click();
  await expect(posted).toContainText("now in transit");
  await page.getByRole("button", { name: `Receive ${sto}`, exact: true }).click();
  await expect(posted).toContainText("(complete)");

  // the shipment is due for billing, at cost plus 6 %
  await page.goto("/#/group/billing");
  const ship = page.getByRole("table", { name: "Shipments" }).getByRole("row", { name: new RegExp(sto) });
  await expect(ship).toContainText("to bill", { timeout: 30_000 });
  const cells = ship.locator("td");
  const q = num(await cells.nth(5).innerText());
  const cost = num(await cells.nth(6).innerText());
  const each = num((await cells.nth(7).innerText()).split("\n")[0]);
  expect(each).toBeCloseTo(cost * 1.06, 1);
  const amount = num(await cells.nth(8).innerText());
  expect(amount).toBeCloseTo(q * each, 0);
  expect(num(await cells.nth(9).innerText())).toBeCloseTo(q * (each - cost), 0);

  await page.getByRole("button", { name: /^Bill 1 shipment$/ }).click();
  await expect(done(page)).toContainText("invoice IC/0001 from Kaveri Kitchenware Pvt Ltd (fictional) to Kaveri Appliances North Pvt Ltd (fictional)", { timeout: 30_000 });
  await expect(page.getByText("Nothing to bill")).toBeVisible();

  // output: the invoice, Pune's GSTIN to North's, place of supply Haryana, in three copies
  await page.getByRole("tab", { name: /Invoices/ }).click();
  const inv = page.getByRole("table", { name: "Inter-company invoices" }).getByRole("row", { name: /IC\/0001/ });
  await expect(inv).toContainText("06 Haryana");
  expect(num(await inv.locator("td").nth(5).innerText())).toBeCloseTo(amount, 0);
  const popup = page.waitForEvent("popup");
  await inv.getByRole("button", { name: "Print IC/0001" }).click();
  const doc = await popup;
  await expect(doc.getByRole("heading", { name: "Tax invoice IC/0001" }).first()).toBeVisible();
  await expect(doc.getByText("GSTIN 27AAJCK4821M1Z3").first()).toBeVisible();
  await expect(doc.getByText("GSTIN 06AAJCK7716N1Z8").first()).toBeVisible();
  await expect(doc.getByText("Original for the recipient")).toBeVisible();
  await expect(doc.getByText("Triplicate for the supplier")).toBeVisible();
  await doc.close();

  // each company's sale and purchase, and the books
  await page.getByRole("tab", { name: /Companies/ }).click();
  const ours = cos.getByRole("row", { name: /Kaveri Kitchenware/ });
  const north = cos.getByRole("row", { name: /Kaveri Appliances North/ });
  // the view is fetched again after each change: read until it has come (a one-off read can see the one before)
  await expect.poll(async () => num(await ours.locator("td").nth(4).innerText()), { timeout: 30_000 }).toBeCloseTo(amount, 0);  // sold to the group
  await expect.poll(async () => num(await north.locator("td").nth(7).innerText()), { timeout: 30_000 }).toBeCloseTo(amount, 0); // bought from the group
  await expect(page.getByRole("table", { name: "Elimination" })).toContainText("Stock in the group's books");
  await page.screenshot({ path: "test-results/group-companies.png", fullPage: true });

  // a cancelled invoice puts the shipment back on the due list
  await page.getByRole("tab", { name: /Invoices/ }).click();
  await inv.getByRole("button", { name: "Cancel IC/0001" }).click();
  await expect(done(page)).toContainText("IC/0001 cancelled: its shipments are on the billing due list again.", { timeout: 30_000 });
  await expect(inv).toContainText("cancelled");
  await page.getByRole("tab", { name: /To bill/ }).click();
  await expect(page.getByRole("button", { name: /^Bill 1 shipment$/ })).toBeVisible();

  // billed again and settled: North pays what it owes, and neither company owes the other anything
  await page.getByRole("button", { name: /^Bill 1 shipment$/ }).click();
  await expect(done(page)).toContainText("invoice IC/0002", { timeout: 30_000 });
  await page.getByRole("tab", { name: /Companies/ }).click();
  await expect.poll(async () => num(await ours.locator("td").nth(9).innerText()), { timeout: 30_000 }).toBeGreaterThanOrEqual(amount - 0.5);   // the invoice, with any tax
  expect(num(await north.locator("td").nth(10).innerText())).toBeCloseTo(num(await ours.locator("td").nth(9).innerText()), 0);
  await page.getByRole("tab", { name: /Invoices/ }).click();
  const inv2 = page.getByRole("table", { name: "Inter-company invoices" }).getByRole("row", { name: /IC\/0002/ });
  await inv2.getByRole("button", { name: "Settle IC/0002" }).click();
  await expect(done(page)).toContainText("paid by Kaveri Appliances North Pvt Ltd (fictional) to Kaveri Kitchenware Pvt Ltd (fictional) for IC/0002; settled.", { timeout: 30_000 });
  await expect(inv2).toContainText("settled");
  await expect(inv2.getByRole("button", { name: "Cancel IC/0002" })).toHaveCount(0);
  await page.getByRole("tab", { name: /Companies/ }).click();
  await expect.poll(async () => num(await ours.locator("td").nth(9).innerText()), { timeout: 30_000 }).toBe(0);
  expect(num(await north.locator("td").nth(10).innerText())).toBe(0);
});
