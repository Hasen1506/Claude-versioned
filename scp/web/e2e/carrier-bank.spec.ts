import { expect, test } from "@playwright/test";

test("import one statement line and recover its grouped carrier match after reload", async ({ page }) => {
  test.setTimeout(90_000);
  const billDate = "2026-01-08";
  const paymentDate = "2026-01-09";
  const company = {
    settings: { company_name: "Carrier statement fixture", planning_start: "2026-01-05", horizon_days: 28, currency: "INR" },
    entities: [{ id: "E1", name: "Paying entity" }],
    locations: [{ id: "W", type: "dc", entity: "E1" }, { id: "C", type: "customer" }],
    lanes: [{ id: "L", origin: "W", destination: "C", modes: [{ mode: "truck_ftl", transit_days: 1 }] }],
    carriers: [{ id: "CR", rates: [{ lane: "L", per_shipment: 90 }] }],
    freight_orders: [40.25, 59.75].map((amount, index) => ({
      id: `FO-${index + 1}`, lane: "L", mode: "truck_ftl", carrier: "CR", ship_from: "W", ship_to: "C", status: "settled",
      planned_on: billDate, shipped_on: billDate, settled_on: billDate, billed: amount, bill: `BILL-${index + 1}`,
      deliveries: [`DL-${index + 1}`], bill_payments: [{ date: paymentDate, amount, reference: "WIRE-GROUP" }],
    })),
  };
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "carrier-statement.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`statement-bundle-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Treasury");
  await page.getByLabel(/^Password/).fill("fixture-only-spring-clover");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);

  let companyUrl = "";
  const matches: { id: string; parameters: { event: { kind: string } } }[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const payload = route.request().postDataJSON();
    if (payload.kind === "carrier_bank" && payload.parameters.event.kind === "match") {
      matches.push(payload);
      if (matches.length === 1) {
        companyUrl = route.request().url().replace(/\/commands$/, "");
        const committed = await route.fetch();
        expect(committed.ok(), await committed.text()).toBe(true);
        return route.abort("failed");
      }
    }
    await route.continue();
  });
  await page.goto("/#/buying/owed");
  await page.getByText("Import statement CSV", { exact: true }).click();
  await page.getByLabel("Statement company").selectOption("E1");
  await page.getByLabel("Import bank account").fill("BANK-1");
  await page.getByLabel("Bank statement CSV").setInputFiles({ name: "statement.csv", mimeType: "text/csv",
    buffer: Buffer.from(`line,date,reference,amount,currency\nJAN/04,${paymentDate},WIRE-GROUP,-100.00,INR\n`) });
  await page.getByRole("button", { name: "Import statement", exact: true }).click();
  await expect(page.getByText("Imported 1 statement lines. Already recorded: 0.")).toBeVisible();
  const table = page.getByRole("table", { name: "Imported bank statements" });
  const source = table.getByRole("row").filter({ hasText: "JAN/04" });
  await source.getByRole("button", { name: "JAN/04" }).click();
  await page.getByLabel("Select cash voucher FO-1/P-1").check();
  const post = page.getByRole("button", { name: "Match selected vouchers" });
  await expect(post).toBeDisabled();
  await page.getByLabel("Select cash voucher FO-2/P-1").check();
  await post.click();
  await expect(page.getByText(/Bank statement operation confirmation is unavailable/)).toBeVisible();
  await page.reload();
  await expect(source).toContainText("Matched (2)");
  await page.getByRole("button", { name: "Retry bank statement operation" }).click();
  await expect(page.getByText("Matched JAN/04 to 2 carrier cash vouchers.")).toBeVisible();
  expect(matches).toHaveLength(2);
  expect(matches[1].id).toBe(matches[0].id);
  expect(matches[1].parameters).toEqual(matches[0].parameters);
  const saved = await (await page.request.get(companyUrl)).json();
  expect(saved.meta.revision).toBe(3);
  expect(saved.dataset.carrier_bank_lines[0].history).toHaveLength(1);
  await source.getByRole("button", { name: "JAN/04" }).click();
  await page.getByRole("button", { name: "Release allocation" }).click();
  await expect(source).toContainText("Unmatched");
  await expect(page.getByLabel("Select cash voucher FO-1/P-1")).toBeVisible();
  await expect(page.getByLabel("Select cash voucher FO-2/P-1")).toBeVisible();
});
