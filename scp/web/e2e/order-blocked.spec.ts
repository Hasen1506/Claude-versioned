import { expect, test } from "@playwright/test";

// N198, used the guide's way on Kaveri. Input: the only supplier of the switch is deleted. Processing: a customer order is
// checked on Selling and on Promise dates. Output: both forms name the part that stops planning and how to put it right,
// instead of pointing at Home. Engine: scp/promise/orders.blocking.

test("an order the data stops names the problem and its fix", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  // input: the switch's only purchasing source is deleted
  await page.goto("/#/data/purchasing_sources/PIR-SWITCH");
  page.once("dialog", (d) => void d.accept());
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(page).toHaveURL(/#\/data\/purchasing_sources$/);

  // processing and output: an order of several lines on Selling
  await page.goto("/#/selling/new");
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-NORTH-TRADE");
  await page.getByLabel("Line 10 product").selectOption("MG-500");
  await page.getByLabel("Line 10 quantity").fill("40");
  await page.getByLabel("Line 10 wanted on").fill("2026-10-20");
  await page.getByRole("button", { name: "Check what can be promised" }).click();
  const said = page.getByRole("alert").filter({ hasText: "cannot be checked" });
  await expect(said).toContainText(/until this is put right: Rotary switch \+ PCB at Pune plant \(Chakan\) is needed but has no way to be supplied/, { timeout: 30_000 });
  await expect(said).toContainText("Say how it gets there");
  await expect(said).not.toContainText("Home");

  // the same on Promise dates' single order
  await page.goto("/#/promise/simulate");
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-NORTH-TRADE");
  await page.getByLabel("Product", { exact: true }).selectOption("MG-500");
  await page.getByLabel("Quantity").fill("40");
  await page.getByLabel("Wanted on").fill("2026-10-20");
  await page.getByRole("button", { name: "Check availability" }).click();
  await expect(page.locator(".banner.error", { hasText: "cannot be checked" })).toContainText("no way to be supplied", { timeout: 30_000 });
});
