import { expect, test, type Page } from "@playwright/test";

// Enterprise 8.4: jobs, not pages. One working day at Kaveri (Mon 28 Sep), five people in turn, each starting from Home
// and moving only by what the screens offer: the rail, the section tabs and the links on the page, never a typed address.
// Each hands work to the next: the planner firms the week's orders, the buyer sends the purchase order firming made,
// the storekeeper confirms the production run, ships the transfer and puts away the goods waiting at Delhi, the
// accountant invoices what was shipped, and the owner opens the month's S&OP cycle.
test.describe.configure({ mode: "serial" });

let page: Page;
const done = () => page.locator(".banner[role=status], .banner.info").last();
// Home, with every answer up to date: a change made on another page is calculated again by the button Home offers
const stale: string[] = [];
const home = async (who: string) => {
  await page.locator("#main-nav").getByRole("link", { name: "Home", exact: true }).click();
  await expect(page.getByRole("region", { name: "Work waiting, by job" })).toBeVisible({ timeout: 45_000 });
  const again = page.getByRole("status").getByRole("button", { name: "Plan everything again" });
  if (await again.isVisible()) {
    stale.push(who);
    await again.click();
  }
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 90_000 });
};
const work = (job: string) => page.getByRole("region", { name: "Work waiting, by job" }).getByLabel(`${job} work`);
const rail = (name: string) => page.locator("#main-nav").getByRole("link", { name: new RegExp(`^${name}`) }).click();
const section = (name: string) => page.getByRole("navigation", { name: /pages$/ }).getByRole("link", { name: new RegExp(`^${name}`) }).click();

test.beforeAll(async ({ browser }) => {
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 90_000 });
});

test.afterAll(async () => { console.log(`Home out of date on arrival for: ${stale.join(", ") || "nobody"}`); await page.close(); });

test("the planner: the week's orders made firm from the work waiting, then the follow-up list", async () => {
  test.setTimeout(180_000);
  await home("the planner");
  // eleven planned orders start inside the 14-day firm zone (before Mon 12 Oct)
  await work("Planning").getByRole("link", { name: "11 planned orders in the firm zone to make firm" }).click();
  await expect(page.getByRole("tab", { name: /Firm orders/, selected: true })).toBeVisible();
  await expect(page.getByText("Firm zone: planned orders starting before Mon 12 Oct (14 days)")).toBeVisible();
  await page.getByRole("button", { name: "Make 11 orders firm" }).click();
  // the purchase among them goes onto a purchase order, left for the buyer to send
  await expect(done()).toContainText(/11 planned orders firmed: .*Purchases went onto 1 purchase order/, { timeout: 60_000 });

  await home("the planner");
  await expect(work("Planning")).not.toContainText("in the firm zone");
  await work("Planning").getByRole("link", { name: /problems? on the follow-up list/ }).click();
  await expect(page.getByRole("tab", { name: /Problems/, selected: true })).toBeVisible();
  await expect(page.getByText(/Money at risk/).first()).toBeVisible({ timeout: 45_000 });
});

test("the buyer: the purchase order firming made is released and sent, and the open one's confirmation recorded", async () => {
  test.setTimeout(180_000);
  await home("the buyer");
  // ₹17.63 L is above the ₹10 L a buyer may order alone: it waits to be released before it can go
  await work("Buying").getByRole("link", { name: "1 purchase order to release" }).click();
  await expect(page.getByRole("tab", { name: /Purchase orders/, selected: true })).toBeVisible();
  await page.getByRole("row", { name: /Rajkot jar works/ }).click();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(done()).toContainText(/approved|released/i, { timeout: 45_000 });
  await page.getByRole("button", { name: "Mark as sent" }).click();
  await expect(done()).toContainText(/sent to Rajkot jar works/, { timeout: 45_000 });

  // Shenzhen's order still waits for its confirmation: they confirm the date asked
  await page.getByRole("row", { name: /PO-4500012871/ }).click();
  await page.getByRole("button", { name: "Record confirmation" }).click();
  await page.getByRole("button", { name: "Save confirmation" }).click();
  await expect(done()).toContainText(/PO-4500012871/, { timeout: 45_000 });

  await home("the buyer");
  await expect(work("Buying")).not.toContainText(/to (send|release)/);
});

test("the storekeeper: Pune's goods in and out for Thursday, then Delhi's goods put away", async () => {
  test.setTimeout(240_000);
  await home("the storekeeper");
  await work("Stores").getByRole("link", { name: /receipts? due in by/ }).click();
  await expect(page.getByRole("tab", { name: /Goods in & out/, selected: true })).toBeVisible();
  await page.getByLabel("Posting date").fill("2026-10-01");
  await page.getByLabel("Place").selectOption({ label: "Pune plant (Chakan)" });
  await page.getByLabel(/only what is due by/).check();
  // the 750 W grinder run (was MO-0018-01) finishes Thu 1 Oct: confirmed, its parts issued
  const run = page.getByRole("row", { name: /was MO-0018-01/ });
  await run.getByRole("button", { name: /^Receive / }).click();
  await expect(page.locator(".banner.info").first()).toContainText(/1,650 Mixer grinder 750 W made at Pune plant \(Chakan\) on Thu 1 Oct \(complete\); 5 parts issued/, { timeout: 45_000 });
  // and the transfer of them to Bhiwandi (was TO-0012-01) leaves the plant
  const transfer = page.getByRole("row", { name: /was TO-0012-01/ });
  await transfer.getByRole("button", { name: /^Ship / }).click();
  await expect(page.locator(".banner.info").first()).toContainText(/1,067 Mixer grinder 750 W shipped from Pune plant \(Chakan\).*1,067 now in transit to Bhiwandi DC \(Mumbai\)/, { timeout: 45_000 });

  // Delhi: the opening stock still waits in goods in
  await home("the storekeeper");
  await work("Stores").getByRole("link", { name: "3 products in goods in at Delhi NCR DC to put away" }).click();
  await expect(page.getByRole("tab", { name: /Put away/, selected: true })).toBeVisible();
  await page.getByRole("button", { name: "Make the put-away tasks" }).click();
  await expect(done()).toContainText("11 put-away tasks at Delhi NCR DC", { timeout: 45_000 });
  await home("the storekeeper");
  await expect(work("Stores")).toContainText("11 warehouse tasks open");
});

test("the accountant: what was shipped is invoiced, and Money shows what is left to collect and pay", async () => {
  test.setTimeout(180_000);
  await home("the accountant");
  await work("Accounts").getByRole("link", { name: "₹33.24 L shipped and not invoiced (2 lines)" }).click();
  await expect(page.getByRole("tab", { name: /Invoices/, selected: true })).toBeVisible();
  await page.getByRole("button", { name: /^Invoice ₹33,23,500/ }).click();
  await expect(done()).toContainText(/INV-/, { timeout: 45_000 });

  await rail("Money");
  await expect(page.getByRole("heading", { name: "To collect and pay" })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByLabel("Accounts work")).not.toContainText("shipped and not invoiced");
  await section("Accounts");
  await expect(page.getByText(/Sales to date/)).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText(/no sales invoiced yet/)).toHaveCount(0);
});

test("the owner: the month's S&OP cycle opened from the rail, its data step signed", async () => {
  test.setTimeout(180_000);
  await rail("S&OP cycle");
  await expect(page.getByRole("heading", { name: "S&OP cycle", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Start the September 2026 cycle" }).click();
  await expect(page.getByRole("tab", { name: "September 2026 · 0 of 5" })).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("No blocking problems", { exact: true })).toBeVisible({ timeout: 45_000 });
  await page.getByRole("button", { name: "Sign off data" }).click();
  await expect(page.getByRole("tab", { name: "September 2026 · 1 of 5" })).toBeVisible({ timeout: 45_000 });

  await rail("Performance");
  await expect(page.getByRole("tab", { name: /KPIs/, selected: true })).toBeVisible();
  // the customer-service measures include the unit fill rate and the order cycle time (N361)
  await expect(page.getByText("Fill rate (units)").first()).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Order fulfilment cycle time").first()).toBeVisible();
});
