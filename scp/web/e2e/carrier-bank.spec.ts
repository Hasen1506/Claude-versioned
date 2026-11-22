import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const billDate = "2026-01-08";
const paymentDate = "2026-01-09";

async function saveCarrierCompany(page: Page, mode: "legacy" | "unpaid" | "registered") {
  const registered = mode === "registered";
  const company = {
    settings: { company_name: "Carrier statement fixture", planning_start: "2026-01-05", horizon_days: 28, currency: "INR" },
    entities: [{ id: "E1", name: "Paying entity" }],
    locations: [{ id: "W", type: "dc", entity: "E1" }, { id: "C", type: "customer" }],
    lanes: [{ id: "L", origin: "W", destination: "C", modes: [{ mode: "truck_ftl", transit_days: 1 }] }],
    carriers: [{ id: "CR", rates: [{ lane: "L", per_shipment: 90 }] }],
    ...(registered && { carrier_bank_accounts: [{ id: "BANK-A", company: "E1", starts_on: paymentDate, opening_minor: 20000, currency: "INR" }] }),
    freight_orders: [40.25, 59.75].map((amount, index) => ({
      id: `FO-${index + 1}`, lane: "L", mode: "truck_ftl", carrier: "CR", ship_from: "W", ship_to: "C", status: "settled",
      planned_on: billDate, shipped_on: billDate, settled_on: billDate, billed: amount, bill: `BILL-${index + 1}`,
      deliveries: [`DL-${index + 1}`],
      ...(mode !== "unpaid" && { bill_payments: [{ date: paymentDate, amount, reference: "WIRE-GROUP",
        ...(registered && { bank_account: "BANK-A" }) }] }),
    })),
  };
  await page.goto("/");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Import a file", exact: true }).click();
  await (await chooser).setFiles({ name: "carrier-statement.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(company)) });
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`statement-${mode}-${Date.now()}@example.invalid`);
  await page.getByLabel("Your name").fill("Treasury");
  await page.getByLabel(/^Password/).fill("fixture-only-spring-clover");
  await page.getByRole("button", { name: "Make the account", exact: true }).click();
  await page.getByRole("button", { name: "Keep it on the server", exact: true }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
}

test("import one statement line and recover its grouped carrier match after reload", async ({ page }) => {
  test.setTimeout(90_000);
  await saveCarrierCompany(page, "legacy");

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

test("tie a registered bank statement period to the carrier journal and reopen it by releasing cash", async ({ page }) => {
  test.setTimeout(90_000);
  await saveCarrierCompany(page, "unpaid");
  await page.goto("/#/buying/owed");
  await page.getByText("Register carrier bank account", { exact: true }).click();
  await page.getByLabel("Bank account company").selectOption("E1");
  await page.getByLabel("Registered bank account ID").fill("BANK-A");
  await page.getByLabel("Bank account first date").fill(paymentDate);
  await page.getByLabel("Bank account opening balance").fill("200.00");
  await page.getByRole("button", { name: "Register account", exact: true }).click();
  await expect(page.getByText("Registered bank account BANK-A.")).toBeVisible();

  let companyUrl = "";
  const attempts: { id: string; parameters: unknown; posting_date: string }[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const payload = route.request().postDataJSON();
    if (payload.action === "pay_bill" && payload.parameters.order === "FO-1") {
      attempts.push({ id: payload.id, parameters: payload.parameters, posting_date: payload.posting_date });
      if (attempts.length === 1) {
        companyUrl = route.request().url().replace(/\/commands$/, "");
        const committed = await route.fetch();
        expect(committed.ok(), await committed.text()).toBe(true);
        return route.abort("failed");
      }
    }
    await route.continue();
  });
  for (const id of ["FO-1", "FO-2"]) {
    const row = page.getByRole("row").filter({ hasText: `BILL-${id.at(-1)}` });
    await row.getByText("Record payment", { exact: true }).click();
    await page.getByLabel(`Payment date ${id}`).fill(paymentDate);
    await page.getByLabel(`Bank reference ${id}`).fill("WIRE-GROUP");
    const paymentButton = page.getByRole("button", { name: `Record payment ${id}` });
    await expect(paymentButton).toBeDisabled();
    await page.getByLabel(`Payment account ${id}`).selectOption("BANK-A");
    await paymentButton.click();
    if (id === "FO-1") {
      await expect(page.getByText(/Payment confirmation is unavailable/)).toBeVisible();
      await page.reload();
      await page.getByRole("button", { name: "Retry carrier payment FO-1" }).click();
    }
    await expect(row.getByText(`paid on ${id}.`, { exact: false })).toBeVisible();
  }
  expect(attempts).toHaveLength(2);
  expect(attempts[1]).toEqual(attempts[0]);

  await page.getByText("Import account statement period", { exact: true }).click();
  await page.getByLabel("Statement period account").selectOption("BANK-A");
  await page.getByLabel("Statement number").fill("SOURCE-JAN");
  await page.getByLabel("Statement period start").fill(paymentDate);
  await page.getByLabel("Statement period end").fill(paymentDate);
  await page.getByLabel("Statement period opening balance").fill("200");
  await page.getByLabel("Statement period closing balance").fill("100");
  await page.getByLabel("Source rows").fill("1");
  const csv = Buffer.from(`\ufeffline,date,reference,amount,currency\r\nSET-1,${paymentDate},WIRE-GROUP,-100.00,INR\r\n`);
  await page.getByLabel("Statement period CSV").setInputFiles({ name: "bank.csv", mimeType: "text/csv", buffer: csv });
  await page.getByRole("button", { name: "Import period", exact: true }).click();
  const accountReport = page.getByRole("table", { name: "Carrier bank account reconciliation" });
  await expect(accountReport).toContainText("Review differences");
  await expect(accountReport).toContainText("1 statement lines · 2 cash vouchers");
  await page.getByRole("button", { name: "SET-1", exact: true }).click();
  await page.getByLabel("Select cash voucher FO-1/P-1").check();
  await page.getByLabel("Select cash voucher FO-2/P-1").check();
  await page.getByRole("button", { name: "Match selected vouchers" }).click();
  await expect(accountReport).toContainText("Reconciled");
  const saved = await (await page.request.get(companyUrl)).json();
  expect(saved.dataset.carrier_bank_periods[0].file_sha256).toBe(createHash("sha256").update(csv).digest("hex"));
  expect(saved.dataset.freight_orders.map((order: { bill_payments: { bank_account: string }[] }) =>
    order.bill_payments.map((p) => p.bank_account))).toEqual([["BANK-A"], ["BANK-A"]]);
  await page.getByRole("button", { name: "Release allocation" }).click();
  await expect(accountReport).toContainText("Review differences");
});

test("import original camt.053, reattach the exact bytes after a lost receipt and reconcile the bank batch", async ({ page }) => {
  test.setTimeout(90_000);
  await saveCarrierCompany(page, "registered");
  const template = readFileSync(new URL("../../engine/tests/fixtures/camt053-booked.xml", import.meta.url), "utf-8");
  const xml = Buffer.from("\ufeff" + template.replaceAll("2026-03-02", billDate).replaceAll("2026-03-03", paymentDate)
    .replaceAll("WIRE-COMB", "WIRE-GROUP").replaceAll("\n", "\r\n"));
  const original = { name: "bank-original.xml", mimeType: "application/xml", buffer: xml };
  const digest = createHash("sha256").update(xml).digest("hex");
  await page.goto("/#/buying/owed");
  await page.getByText("Import original camt.053 statement", { exact: true }).click();
  await page.getByLabel("Original statement account").selectOption("BANK-A");
  await page.getByLabel("Original camt.053 file").setInputFiles(original);
  await page.getByRole("button", { name: "Link bank source" }).click();
  await expect(page.getByText("Linked camt.053 source for BANK-A.")).toBeVisible();

  let companyUrl = "";
  const attempts: { id: string; parameters: unknown; posting_date: string }[] = [];
  await page.route("**/api/companies/*/commands", async (route) => {
    const payload = route.request().postDataJSON();
    if (payload.kind === "carrier_bank" && payload.parameters.event.kind === "import_camt") {
      attempts.push({ id: payload.id, parameters: payload.parameters, posting_date: payload.posting_date });
      if (attempts.length === 1) {
        companyUrl = route.request().url().replace(/\/commands$/, "");
        const committed = await route.fetch();
        expect(committed.ok(), await committed.text()).toBe(true);
        return route.abort("failed");
      }
    }
    await route.continue();
  });
  await page.getByRole("button", { name: "Import original statement" }).click();
  await expect(page.getByText(/Bank statement operation confirmation is unavailable/)).toBeVisible();
  const pending = await page.evaluate(() => Object.entries(sessionStorage)
    .find(([key]) => key.startsWith("scp.carrier-bank.pending.v1:"))?.[1]);
  expect(pending).toContain(digest);
  expect(pending).not.toContain("PRIVATE-FIXTURE-XML-MARKER");

  await page.reload();
  const retry = page.getByRole("button", { name: "Retry bank statement operation" });
  await expect(retry).toBeDisabled();
  await page.getByLabel("Original camt.053 file").setInputFiles({ ...original, buffer: Buffer.concat([xml, Buffer.from("\n")]) });
  await retry.click();
  await expect(page.getByText("Choose the exact original camt.053 file to retry.")).toBeVisible();
  expect(attempts).toHaveLength(1);
  await page.getByLabel("Original camt.053 file").setInputFiles(original);
  await retry.click();
  await expect(page.getByText("Imported statement FIXTURE-STMT-001.")).toBeVisible();
  expect(attempts[1]).toEqual(attempts[0]);
  const receipt = await page.request.get(`${companyUrl}/commands`, { params: { id: attempts[0].id } });
  expect((await receipt.json()).parameters.event).toEqual({
    kind: "import_camt", account: "BANK-A", file_sha256: digest, byte_count: xml.length,
  });
  const accountReport = page.getByRole("table", { name: "Carrier bank account reconciliation" });
  await expect(accountReport).toContainText("Review differences");
  await accountReport.getByText("Original camt.053", { exact: true }).click();
  await expect(accountReport.getByText(digest)).toBeVisible();
  await page.getByRole("button", { name: "SVCR-00001", exact: true }).click();
  await page.getByLabel("Select cash voucher FO-1/P-1").check();
  await page.getByLabel("Select cash voucher FO-2/P-1").check();
  await page.getByRole("button", { name: "Match selected vouchers" }).click();
  await expect(accountReport).toContainText("Reconciled");
});
