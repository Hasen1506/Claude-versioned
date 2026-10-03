import { expect, test, type Page } from "@playwright/test";

// Phase Q: an owner makes a key, the ERP sends customer orders with it, the message log says what became of each,
// the company's history has the ERP's save, a scheduled import is set up and run, and the e-mail tab says what the
// server sends.

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/status of (422|409)/.test(m.text())) errors.push(m.text()); });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

async function ownerOnServer(page: Page): Promise<{ token: string; cid: string }> {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(`connect-${Date.now()}@kaveri.in`);
  await page.getByLabel("Your name").fill("Asha Owner");
  await page.getByLabel(/^Password/).fill("kaveri-2026");
  await page.getByRole("button", { name: "Make the account" }).click();
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
  const token = await page.evaluate(() => JSON.parse(localStorage.getItem("scp.session.v1") ?? "{}").token as string);
  const list = await (await page.request.get("/api/companies", { headers: { Authorization: `Bearer ${token}` } })).json();
  return { token, cid: list[0].id as string };
}

test("connections: a key for the ERP, its orders taken and refused line by line, a scheduled import, e-mail", async ({ page }) => {
  page.on("dialog", (d) => d.accept());
  const { cid } = await ownerOnServer(page);

  await page.locator(".rail-foot a", { hasText: "Connections" }).click();
  await expect(page.getByRole("heading", { name: "Connections" })).toBeVisible();
  await expect(page.locator("main")).toContainText("Nothing yet");

  // the owner makes a key for SAP: shown once
  await page.getByRole("tab", { name: "Keys" }).click();
  await page.getByLabel("Name of the system").fill("SAP");
  await page.getByRole("button", { name: "Make a key" }).click();
  const shown = page.getByLabel("The new key");
  await expect(shown).toHaveValue(/^scpk_/);
  const key = await shown.inputValue();
  await expect(page.locator("table")).toContainText("SAP");
  await expect(page.locator("table")).toContainText("never");

  // SAP sends two customer orders: one taken, one with a product this company does not have
  const r = await page.request.post(`/api/companies/${cid}/erp/orders`, { headers: { Authorization: `Bearer ${key}` }, data: {
    message_id: "SAP-0001", orders: [
      { number: "4711", customer: "CUS-WEST-TRADE", order_date: "2026-09-28", lines: [{ product: "MG-500", qty: 40, date: "2026-10-12" }] },
      { number: "4712", customer: "CUS-WEST-TRADE", order_date: "2026-09-28", lines: [{ product: "NOPE", qty: 1, date: "2026-10-12" }] },
    ] } });
  expect(r.ok()).toBe(true);
  expect((await r.json()).message.summary).toBe("2 orders: 1 taken, 1 refused");

  // the log says what became of each, and the save is in the history
  await page.getByRole("tab", { name: "Messages" }).click();
  const row = page.locator("tr", { hasText: "SAP (key)" }).first();
  await expect(row).toContainText("partly taken");
  await expect(row).toContainText("2 orders: 1 taken, 1 refused");
  await expect(row).toContainText("message SAP-0001");
  await row.getByRole("button", { name: "2 lines" }).click();
  await expect(page.locator("main")).toContainText(/SO-\d+ taken for West trade distributors: 1 line/);
  await expect(page.locator("main")).toContainText("line 1: there is no product 'NOPE'");
  await page.getByRole("link", { name: "History" }).first().click();
  await expect(page.locator("main")).toContainText("orders from SAP (key) (message SAP-0001)");

  // a scheduled import: an address inside the server's own network is not read
  await page.goto("/#/connections/imports");
  await page.getByRole("button", { name: "New import" }).click();
  await page.getByLabel("Import name").fill("Open orders from SAP");
  await page.getByLabel("Source").fill("http://127.0.0.1:9/orders.csv");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("status")).toContainText("Open orders from SAP saved: it runs every day at 06:00.");
  await page.getByRole("button", { name: "Run now" }).click();
  await expect(page.getByRole("status")).toContainText("127.0.0.1 is inside the server's own network");
  await expect(page.locator("table")).toContainText("failed");

  // this server sends no mail: said plainly, reminders cannot be switched on
  await page.getByRole("tab", { name: "E-mail" }).click();
  await expect(page.locator("main")).toContainText("This server sends no mail");
  await expect(page.getByRole("checkbox", { name: "Send worklist reminders" })).toBeDisabled();

  // the key is withdrawn: it no longer works
  await page.getByRole("tab", { name: "Keys" }).click();
  await page.getByRole("button", { name: "Withdraw SAP" }).click();
  await expect(page.locator("main")).toContainText("No key yet.");
  const again = await page.request.get(`/api/companies/${cid}/erp/purchase-orders`, { headers: { Authorization: `Bearer ${key}` } });
  expect(again.status()).toBe(401);

  // at phone width every tab fits
  await page.setViewportSize({ width: 390, height: 844 });
  for (const t of ["messages", "keys", "imports", "mail"]) {
    await page.goto(`/#/connections/${t}`);
    await expect(page.getByRole("heading", { name: "Connections" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  }
});

test("scheduled import changes preserve credentials only at the same origin and can clear them", async ({ page }) => {
  const { token, cid } = await ownerOnServer(page);
  const headers = { Authorization: `Bearer ${token}` };
  await page.goto("/#/connections/imports");
  await page.getByRole("button", { name: "New import" }).click();
  await page.getByLabel("Import name").fill("ERP stock");
  await page.getByLabel("What it brings").selectOption("stock");
  await page.getByLabel("Source").fill("https://erp.example.com/stock.csv");
  await page.getByLabel("Authorization header").fill("Bearer TEST-ONLY");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("status")).toContainText("ERP stock saved");
  const saved = async () => (await (await page.request.get(`/api/companies/${cid}/imports`, { headers })).json()).jobs[0];
  expect((await saved()).header_names).toEqual(["Authorization"]);

  await page.getByRole("button", { name: "Change", exact: true }).click();
  await expect(page.getByLabel("Authorization header")).toHaveValue("");
  await page.getByLabel("Source").fill("https://erp.example.com/next.csv");
  const sameOrigin = page.waitForRequest((r) => r.method() === "PUT" && /\/imports\//.test(r.url()));
  await page.getByRole("button", { name: "Save the import" }).click();
  expect((await sameOrigin).postDataJSON()).not.toHaveProperty("headers");
  await expect(page.getByRole("button", { name: "Save the import" })).toHaveCount(0);
  expect((await saved()).header_names).toEqual(["Authorization"]);

  await page.getByRole("button", { name: "Change", exact: true }).click();
  await page.getByLabel("Source").fill("https://other.example.com/stock.csv");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("button", { name: "Save the import" })).toHaveCount(0);
  expect((await saved()).header_names).toEqual([]);

  await page.getByRole("button", { name: "Change", exact: true }).click();
  await page.getByLabel("Authorization header").fill("Bearer REPLACEMENT-TEST");
  await page.getByRole("button", { name: "Save the import" }).click();
  await expect(page.getByRole("button", { name: "Save the import" })).toHaveCount(0);
  expect((await saved()).header_names).toEqual(["Authorization"]);

  await page.getByRole("button", { name: "Change", exact: true }).click();
  await page.getByRole("checkbox", { name: "Remove saved request headers" }).check();
  const clear = page.waitForRequest((r) => r.method() === "PUT" && /\/imports\//.test(r.url()));
  await page.getByRole("button", { name: "Save the import" }).click();
  expect((await clear).postDataJSON().headers).toEqual({});
  await expect(page.getByRole("button", { name: "Save the import" })).toHaveCount(0);
  expect((await saved()).header_names).toEqual([]);
});
