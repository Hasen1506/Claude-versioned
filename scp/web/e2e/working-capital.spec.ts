// Working capital on the Performance page: average stock rebuilt from the journal for DIO and turns, DSO counted back
// through the billing, what customers and suppliers are owed by days past due, and a weekly cash-to-cash trend.
// Input: sixteen weeks of goods issued, customer invoices and supplier invoices added to an example's journal.
// Processing: the Performance page recalculated. Output: the measures, their week-by-week trend and the ageing.
import { expect, test } from "@playwright/test";

test("working capital: average stock, count-back DSO, ageing and a weekly cash-to-cash trend from the company's records", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  // the input: sixteen weeks of records before the planning start, put in the working copy as an import would
  await page.evaluate(() => {
    const ds = JSON.parse(localStorage.getItem("scp.dataset.v1")!);
    const start = new Date(ds.settings.planning_start + "T00:00:00Z");
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    const add = (d: Date, days: number) => new Date(d.getTime() + days * 86400_000);
    const sold = ds.location_products.filter((lp: { location: string; on_hand?: number }) => lp.location === "DC-BHIWANDI" && (lp.on_hand ?? 0) > 0);
    for (let w = 16; w >= 1; w--) {
      const day = add(start, -7 * w);
      for (const lp of sold) {
        ds.movements.push({ id: `WC-G${w}-${lp.product}`, date: iso(day), type: "sale", location: lp.location, product: lp.product,
          qty: Math.round(lp.on_hand / 8), counterparty: "CUS-ECOM" });
      }
      // a weekly invoice paid after 30 days (the last six still open), and a fortnightly supplier invoice paid after 45
      ds.invoices.push({ id: `WC-I${w}`, customer: "CUS-ECOM", date: iso(day), due_date: iso(add(day, 30)),
        lines: [{ product: "KT-15", qty: 400, price: 1190 }], payments: w > 6 ? [{ date: iso(add(day, 30)), amount: 400 * 1190 * 1.18 }] : [] });
      if (w % 2 === 0) {
        ds.supplier_invoices.push({ id: `WC-S${w}`, supplier: "SUP-STAMP", date: iso(day), due_date: iso(add(day, 45)),
          lines: [{ order: "PO-WC", product: "RM-STAMP", qty: 4000, price: 118 }],
          payments: w > 8 ? [{ date: iso(add(day, 45)), amount: 4000 * 118 * 1.18 }] : [] });
      }
    }
    localStorage.setItem("scp.dataset.v1", JSON.stringify(ds));
  });
  await page.reload();

  // the processing: the Performance page worked out again
  await page.goto("/#/tower/kpis/cash_to_cash");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  // the output: the cycle, how it moved week by week, and where its parts come from
  const trend = page.getByRole("table", { name: "Cash-to-cash cycle week by week" });
  await expect(trend).toBeVisible({ timeout: 60_000 });
  await expect(trend.locator("tbody tr")).toHaveCount(12);
  await expect(trend.locator("tbody tr").first()).toContainText(/\d+(\.\d)? d/);              // the latest week has a value
  await expect(page.locator("main svg").first()).toBeVisible();                               // drawn as a line
  await expect(page.locator("main")).toContainText(/DIO [\d,.]+ \+ DSO [\d,.]+ − DPO [\d,.]+ days/);

  await page.goto("/#/tower/kpis/dio");
  await expect(page.locator("main")).toContainText(/average stock [\d,]+ INR over those days \(on the planning start [\d,]+ INR\)/);

  await page.goto("/#/tower/kpis/dso");
  await expect(page.locator("main")).toContainText(/Count-back/);
  await expect(page.locator("main")).toContainText(/by the average of the period [\d.]+ days/);
  const owed = page.getByRole("table", { name: "Receivables ageing" });
  await expect(owed).toContainText("not yet due");
  await expect(owed).toContainText("1–30 days overdue");

  await page.goto("/#/tower/kpis/dpo");
  await expect(page.getByRole("table", { name: "Payables ageing" })).toContainText("not yet due");
});
