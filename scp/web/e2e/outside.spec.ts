import { expect, test, type Page } from "@playwright/test";

// Enterprise 7.1, used the guide's way on Kaveri. Input: the winding machines are full, so MO-100461 (600 motors of
// 750 W) goes to Bhosari winding works on a job-work challan; a marketplace order for 500 kettles is bought from Vasai
// appliance works, who ship it to the marketplace's warehouse. Processing: the parts the bill needs, out of the plant
// as issues to the order and held at the job worker; 580 motors back using up their parts, unused sets back in stock;
// the kettles' dispatch billed to the customer and matched against the supplier. Output: the challan in three
// copies, the stock at the job worker and its GST limit, ITC-04, and the third-party order dispatched, billed and
// invoiced. Engine: scp/jobwork, scp/dropship.
//
// Wire per good motor 0.55 kg / 0.985 (motors lost) / 0.98 (wire lost) = 0.5698; sets 1 / 0.985 / 0.99 = 1.0255.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const done = (page: Page) => page.locator('.banner[role="status"]').last();

test("parts sent to a job worker on a challan, the motors back, the unused sets returned, ITC-04", async ({ page }) => {
  test.setTimeout(240_000);
  await openKaveri(page);

  // input: MO-100461's parts for Bhosari winding works
  await page.goto("/#/outside");
  await expect(page.getByRole("heading", { name: "Job work & drop-ship" })).toBeVisible();
  await page.getByLabel("Production order").selectOption("MO-100461");
  const parts = page.getByRole("table", { name: "Parts to send" });
  await expect(parts.getByLabel("Send RM-CU-WIRE")).toHaveValue("341.862633", { timeout: 30_000 });   // 600 × 0.5698 kg
  await expect(parts.getByLabel("Send RM-STAMP")).toHaveValue("616");                               // 615.29, whole sets
  await page.getByLabel("Job worker").selectOption("SUP-WIND");
  await page.getByLabel("Job charge per unit").fill("18");
  await page.getByLabel("Vehicle").fill("MH12 AB 4521");
  await page.getByRole("button", { name: "Send on a challan" }).click();
  await expect(done(page)).toContainText("Challan JW-00001: 341.86 kg Enamelled copper wire, 616 Stator/rotor lamination set sent to Bhosari winding works for MO-100461 on Mon 28 Sep 2026", { timeout: 30_000 });
  await expect(done(page)).toContainText("Back by Tue 28 Sep 2027");          // a year for inputs

  // processing: the challan holds the parts at the job worker
  const challans = page.getByRole("table", { name: "Challans" });
  const jw = challans.getByRole("row", { name: /JW-00001/ });
  await expect(jw).toContainText("at job worker");
  await expect(jw).toContainText("GSTIN 27AAKFB4417M1Z5");
  await expect(jw).toContainText("365 days left");
  const stock = page.getByRole("table", { name: "Stock at job workers" });
  await expect(stock.getByRole("row", { name: /Stator\/rotor lamination set/ })).toContainText("616");

  // 580 motors back: 580 × 0.5698 = 330.47 kg wire and 580 × 1.0255 = 594.78 sets used up there
  await jw.getByLabel("Back processed JW-00001").fill("580");
  await jw.getByLabel("Their challan JW-00001").fill("BWW/114");
  await jw.getByRole("button", { name: "Goods back JW-00001" }).click();
  await expect(done(page)).toContainText("JW-00001: 580 Motor assembly 750 W back from Bhosari winding works on Mon 28 Sep 2026 (their BWW/114), made from 330.47 kg Enamelled copper wire, 594.78 Stator/rotor lamination set", { timeout: 30_000 });
  await expect(done(page)).toContainText("Job charge INR 10,440.00 due");     // 580 × 18
  // five sets back as they went: 616 − 594.78 − 5 = 16.22 left there
  await jw.getByLabel("Part of JW-00001").selectOption("RM-STAMP");
  await jw.getByLabel("Part quantity JW-00001").fill("5");
  await jw.getByRole("button", { name: "Back unused JW-00001" }).click();
  await expect(done(page)).toContainText("JW-00001: 5 Stator/rotor lamination set back unused from Bhosari winding works", { timeout: 30_000 });
  await expect(done(page)).toContainText("16.22 Stator/rotor lamination set");
  await expect(done(page)).toContainText("11.40 kg Enamelled copper wire");    // 341.86 − 330.47
  await page.screenshot({ path: "test-results/outside-jobwork.png", fullPage: true });

  // output: ITC-04 for the half year, and the job charge waiting for the job worker's invoice
  await page.getByRole("tab", { name: /ITC-04/ }).click();
  await expect(page.getByText("ITC-04 for Apr–Sep 2026")).toBeVisible();
  const sent = page.getByRole("table", { name: "Sent to job workers" });
  await expect(sent.getByRole("row", { name: /Enamelled copper wire/ })).toContainText("85441110");
  await expect(sent.getByRole("row", { name: /Enamelled copper wire/ })).toContainText("KGS");
  const back = page.getByRole("table", { name: "Back from job workers" });
  await expect(back.getByRole("row", { name: /Motor assembly 750 W/ })).toContainText("BWW/114");
  await expect(back.getByRole("row", { name: /Motor assembly 750 W/ })).toContainText("processed goods");
  await expect(back.getByRole("row", { name: /lamination/ })).toContainText("inputs");
  await page.goto("/#/buying/invoices");
  const charge = page.getByRole("row", { name: /JW-00001/ });
  await expect(charge).toContainText("Bhosari winding works", { timeout: 45_000 });
  await expect(charge).toContainText("580₹18");                 // 580 back at 18 a motor
});

test("a third-party order: sent, dispatched by the supplier, billed to the customer and matched", async ({ page }) => {
  test.setTimeout(240_000);
  await openKaveri(page);
  await page.goto("/#/outside/dropship");
  await expect(page.getByRole("heading", { name: "Job work & drop-ship" })).toBeVisible();

  // input: 500 kettles for the marketplace, shipped by Vasai appliance works at 742 each
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-ECOM");
  await page.getByLabel("Product", { exact: true }).selectOption("KT-15");
  await page.getByLabel("Quantity", { exact: true }).fill("500");
  await page.getByLabel("Wanted by").fill("2026-10-16");
  await page.getByLabel("Shipped by").selectOption("SUP-VASAI");
  await page.getByLabel("Purchase price").fill("742");
  await page.getByLabel("Their order number").fill("FK-PO-55120");
  await page.getByRole("button", { name: "Take the order" }).click();
  // 500 × (1,190 − 742) = 224,000
  await expect(done(page)).toContainText("TP-00001: 500 Electric kettle 1.5 L for E-commerce marketplaces by Fri 16 Oct, shipped by Vasai appliance works: sold at INR 1,190.00, bought at INR 742.00, INR 224,000.00 margin.", { timeout: 30_000 });
  const orders = page.getByRole("table", { name: "Third-party orders" });
  const tp = orders.getByRole("row", { name: /TP-00001/ });
  await expect(tp).toContainText("to send");

  // processing: the purchase order goes out; the supplier dispatches 300
  await tp.getByRole("button", { name: "Send TP-00001" }).click();
  await expect(done(page)).toContainText("TP-00001 sent to Vasai appliance works", { timeout: 30_000 });
  await tp.getByLabel("Dispatched TP-00001").fill("300");
  await tp.getByLabel("Dispatch note TP-00001").fill("LR 66012");
  await tp.getByRole("button", { name: "Dispatch TP-00001" }).click();
  await expect(done(page)).toContainText("Vasai appliance works dispatched 300 Electric kettle 1.5 L to E-commerce marketplaces on Mon 28 Sep (their LR 66012) (200 still to come).", { timeout: 30_000 });
  await expect(tp).toContainText("partly dispatched");
  await expect(page.locator(".banner", { hasText: "Bill them" })).toContainText("TP-00001: 300 dispatched");

  // output: billed on Selling at 300 × 1,190 = 357,000, and the supplier's 300 × 742 waiting on Buying
  await page.goto("/#/selling/bill");
  const due = page.getByRole("row", { name: /TP-00001/ });
  await expect(due).toContainText("₹3,57,000.00", { timeout: 45_000 });
  await page.getByRole("button", { name: /^Invoice ₹/ }).click();
  await expect(page.locator('.banner[role="status"]').last()).toContainText("to E-commerce marketplaces", { timeout: 30_000 });
  await page.goto("/#/buying/invoices");
  const owed = page.getByRole("row", { name: /TP-00001/ });
  await expect(owed).toContainText("Vasai appliance works", { timeout: 45_000 });
  await expect(owed).toContainText("300₹742");
  await page.goto("/#/outside/dropship");
  const row = page.getByRole("table", { name: "Third-party orders" }).getByRole("row", { name: /TP-00001/ });
  await expect(row).toContainText("300 · 300 · 0");
  // the last 195 and the order closes five short: the margin is on what went, 495 × 448 = 221,760
  await row.getByLabel("Dispatched TP-00001").fill("195");
  await row.getByLabel("Last dispatch TP-00001").check();
  await row.getByRole("button", { name: "Dispatch TP-00001" }).click();
  await expect(done(page)).toContainText("(closed 5 short)", { timeout: 30_000 });
  await expect(row).toContainText("₹2,21,760.00");
  await expect(row).toContainText("dispatched");
  await page.screenshot({ path: "test-results/outside-dropship.png", fullPage: true });
});
