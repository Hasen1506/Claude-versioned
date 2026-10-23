import { expect, test } from "@playwright/test";

// Enterprise 8.3, transport T19 (CONFORMANCE §7), used the guide's way on Kaveri. Input: the plan's requisition for
// 14,000 rotary switches from Shenzhen, bought FOB Shenzhen (the main carriage is ours), ordered and sent; the sea lane
// to Pune takes 30 days. Processing: transport plans what is to load, now with the collections. Output: the switches
// load at Shenzhen on 5 Nov (due 5 Dec), 1,120 kg and 1.4 m³, at the lane's own cost: 45,000 + 1.4 × 6,500.
test("a purchase bought FOB is collected: transport plans the sea freight from the supplier", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  await page.goto("/#/buying");
  await page.getByText("Show later ones too").click();
  await page.getByLabel("Find requisitions").fill("PR-0027-01");
  await page.getByRole("button", { name: "Create purchase orders (1)" }).click();
  const made = page.locator('.banner[role="status"]');
  await expect(made).toContainText(/PO-\d+ to Shenzhen electro-components/, { timeout: 45_000 });
  await made.getByRole("link").first().click();
  await page.getByRole("button", { name: "Mark as sent" }).click();
  await expect(page.getByRole("button", { name: "Mark as sent" })).toHaveCount(0, { timeout: 30_000 });

  // the collection loads 30 days before it is due, beyond the 7 days transport looks ahead: look 60 days ahead
  await page.goto("/#/transport/carriers");
  await page.getByLabel(/^Horizon days/i).fill("60");
  await page.getByRole("tab", { name: /To load/ }).click();
  const vehicles = page.getByRole("table", { name: "Vehicles to load" });
  const sea = vehicles.getByRole("row", { name: /Shenzhen/ });
  await expect(sea).toContainText(/collect from the supplier: PO-\d+-10/, { timeout: 45_000 });
  await expect(sea).toContainText("Thu 5 Nov");
  await expect(sea).toContainText("1,120 kg");
  await expect(sea).toContainText("₹54,100.00");
  await expect(sea).toContainText("no carrier: the lane's cost");
});
