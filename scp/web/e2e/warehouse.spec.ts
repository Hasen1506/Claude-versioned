import { expect, test, type Page } from "@playwright/test";

// Enterprise 6.1, used the guide's way on Kaveri's Delhi DC. Input: stock taken at go-live in no bin, two sales orders
// due; processing: put-away by the rules, a wave over the deliveries, every task confirmed by scanning bin and product
// on the phone page (one pick short); output: the stock in its bins, the pick list in walk order, the delivery shipped
// with what was picked. Engine: scp/warehouse.

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

const done = (page: Page) => page.locator('.banner[role="status"]').last();

async function scan(page: Page, label: "Scan the bin" | "Scan the product", code: string) {
  const f = page.getByLabel(label);
  await f.fill(code);
  await f.press("Enter");                       // a hand-held scanner types the code and Enter
}

test("put away at go-live, a wave picked by scanning on the phone, one pick short, the delivery shipped", async ({ page }) => {
  test.setTimeout(240_000);
  await openKaveri(page);

  // input: every unit at the Delhi DC is in no bin yet
  await page.goto("/#/warehouse");
  await expect(page.getByRole("heading", { name: "Warehouse" })).toBeVisible();
  await expect(page.getByLabel("Warehouse place")).toHaveValue("DC-DELHI");
  await expect(page.getByRole("table", { name: "Stock in no bin" })).toContainText("Electric kettle 1.5 L");
  await expect(page.getByRole("table", { name: "Stock by bin" }).locator("tbody tr")).toHaveCount(16);   // 16 empty bins

  // processing: the put-away proposal, by the rule shelves then rack, two shelves a product
  await page.getByRole("tab", { name: /Put away/ }).click();
  const prop = page.getByRole("table", { name: "Put-away proposal" });
  await expect(prop.locator("tbody tr")).toHaveCount(11, { timeout: 30_000 });
  await expect(prop.locator("tbody tr").first()).toContainText("S-01-01");
  await page.getByRole("button", { name: "Make the put-away tasks" }).click();
  await expect(done(page)).toContainText("11 put-away tasks at Delhi NCR DC", { timeout: 30_000 });

  // the phone: one task at a time, read the bin, then the product (a wrong one is refused), then the quantity
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/scan/DC-DELHI");
  const card = page.getByRole("region", { name: /Task WT-/ });
  await expect(card).toContainText("Put away");
  await expect(page.getByLabel("Go to")).toContainText("S-01-01");
  await scan(page, "Scan the bin", "S-01-01");
  await scan(page, "Scan the product", "8906011250005");              // the 500 W grinder's label
  await expect(page.getByRole("alert")).toContainText("That is Mixer grinder 500 W: this task is for Electric kettle 1.5 L");
  await scan(page, "Scan the product", "8906011250029");              // the kettle's
  await expect(page.getByLabel("Quantity moved")).toHaveValue("300");
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(done(page)).toContainText("300 Electric kettle 1.5 L put away in S-01-01", { timeout: 30_000 });
  await expect(page.getByLabel("Go to")).toContainText("S-01-02");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: "test-results/warehouse-scan.png" });

  // the rest confirmed from the desk, in walk order
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/#/warehouse/tasks/DC-DELHI");
  const tasks = page.getByRole("table", { name: "Open warehouse tasks" });
  await expect(tasks.locator("tbody tr")).toHaveCount(10);
  for (let left = 10; left > 0; left--) {
    await tasks.getByRole("button", { name: /^Confirm WT-/ }).first().click();
    await expect(tasks.locator("tbody tr")).toHaveCount(left - 1, { timeout: 30_000 }).catch(async () => {
      await expect(page.getByText("No open tasks")).toBeVisible();
    });
  }
  await page.getByRole("tab", { name: /Stock by bin/ }).click();
  const bins = page.getByRole("table", { name: "Stock by bin" });
  await expect(bins.getByRole("row", { name: /^S-01-01 / })).toContainText("Electric kettle 1.5 L");
  await expect(page.getByRole("table", { name: "Stock in no bin" })).toHaveCount(0);

  // input: the orders due in the next ten days go on deliveries (the window is set where it is shown)
  await page.goto("/#/selling/deliver");
  await page.getByLabel("Days ahead to ship").fill("10");
  await expect(page.getByRole("button", { name: /Make deliveries for \d+ lines/ })).toBeEnabled({ timeout: 45_000 });
  await page.getByRole("button", { name: /Make deliveries for \d+ lines/ }).click();
  await expect(done(page)).toContainText(/from Delhi NCR DC/, { timeout: 45_000 });

  // processing: a wave over the Delhi deliveries, its pick list in walk order
  await page.goto("/#/warehouse/picking/DC-DELHI");
  await page.getByRole("button", { name: /Make a wave of 1 delivery/ }).click();
  await expect(done(page)).toContainText(/Wave WV-0001: 1 delivery, \d+ picks from \d+ bins, in walk order/, { timeout: 30_000 });
  const pl = page.getByRole("table", { name: "Pick list WV-0001" });
  await expect(pl).toBeVisible();
  const order = await pl.locator("tbody tr td:first-child").allInnerTexts();
  expect(order[0]).toMatch(/^S-01-0[3-6]$/);                      // the picking shelves first, the rack after
  await page.screenshot({ path: "test-results/warehouse-picklist.png", fullPage: true });

  // the first pick on the phone: the wrong bin is refused, then 20 fewer found than asked
  await page.getByRole("link", { name: "Pick it on a phone" }).click();
  await expect(page.getByText("wave WV-0001")).toBeVisible();
  const first = (await page.getByLabel("Go to").innerText()).replace(/^From\s+/, "").trim();
  await scan(page, "Scan the bin", "R-02-04");
  await expect(page.getByRole("alert")).toContainText(`That is bin R-02-04: go to ${first}`);
  await scan(page, "Scan the bin", first);
  const want = await card.locator(".scan-prod").innerText();
  const code = want.includes("750 W") ? "8906011250012" : "8906011250005";
  await scan(page, "Scan the product", code);
  const asked = Number(await page.getByLabel("Quantity moved").inputValue());
  await page.getByLabel("Quantity moved").fill(String(asked - 20));
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(done(page)).toContainText(`20 short. Count bin ${first}`, { timeout: 30_000 });

  // the rest in full from the pick list, then the delivery ships what was picked
  await page.goto("/#/warehouse/picking/DC-DELHI");
  const rows = pl.getByRole("button", { name: /^Picked .* in full$/ });
  await expect(rows.first()).toBeVisible();
  for (let n = await rows.count(); n > 0; n--) {
    await rows.first().click();
    await expect(rows).toHaveCount(n - 1, { timeout: 30_000 });
  }
  await expect(page.getByText("picked", { exact: true })).toBeVisible();
  await expect(done(page)).toContainText(/is picked, short: SO-\d+ \d+ of \d+: pack it and ship it/);
  const dl = /DL-\d+/.exec(await done(page).innerText())![0];
  await page.goto(`/#/selling/deliver/${dl}`);
  await page.getByRole("button", { name: "Ship it" }).click();
  await expect(done(page)).toContainText(new RegExp(`${dl} shipped to`), { timeout: 45_000 });

  // output: what left came off the bins it was picked from; nothing staged is left behind
  await page.goto("/#/warehouse/bins/DC-DELHI");
  await expect(page.getByRole("table", { name: "Stock by bin" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Stock in no bin" })).toHaveCount(0);

  // Enterprise 8.3 (CONFORMANCE §6, W7): the picks emptied the grinders' shelves; each is kept for its product and
  // refilled from the rack at 100. S-01-03 holds the 20 the short pick left, S-01-04 100, S-01-05 none: 280, 200
  // and 300 up to their 300, from the rack first in first.
  await page.getByRole("tab", { name: "Refill picking bins" }).click();
  const need = page.getByRole("table", { name: "Bins to refill" });
  await expect(need.locator("tbody tr")).toHaveCount(3, { timeout: 30_000 });
  await expect(need.getByRole("row", { name: /^S-01-03 / })).toContainText(/Mixer grinder 500 W\s*20\s*100\s*300\s*280/);
  await expect(need.getByRole("row", { name: /^S-01-04 / })).toContainText(/100\s*100\s*300\s*200/);
  await expect(need.getByRole("row", { name: /^S-01-05 / })).toContainText(/Mixer grinder 750 W\s*0\s*100\s*300\s*300/);
  await expect(page.getByRole("table", { name: "Refill moves" }).locator("tbody tr")).toHaveCount(4);
  await page.getByRole("button", { name: "Make the refill tasks" }).click();
  await expect(done(page)).toContainText("4 refill tasks at Delhi NCR DC: 280 Mixer grinder 500 W from R-01-02 to S-01-03", { timeout: 30_000 });
  await expect(page.getByText("No bin needs refilling")).toBeVisible();      // the open refills count
});

test("bins, storage types and put-away rules are master data", async ({ page }) => {
  await openKaveri(page);
  await page.goto("/#/data/bins");
  await expect(page.getByRole("link", { name: /Storage bins/ })).toBeVisible();
  await expect(page.getByRole("cell", { name: "R-02-04" })).toBeVisible();
  await page.goto("/#/data/putaway_rules");
  await expect(page.getByRole("cell", { name: "SHELF → RACK" })).toBeVisible();
});
