import { expect, test } from "@playwright/test";

// Enterprise 8.3, selling S11 (CONFORMANCE §5), used the guide's way on Kaveri. Input: an e-commerce order for 3,000
// of the 500 W grinder wanted Thu 1 Oct, and the company's rule that the 750 W grinder may ship in its place at the
// 500 W price. Processing: the order is promised from Bhiwandi's free stock (2,098 on time; the rest on new supply
// later), and the 750 W grinder's stock still free that day after every promise is offered for the part not on time.
// Output: 567 of the 902 can ship as the 750 W grinder on the date asked, and one click moves them to a line of it.
test("an order short of one grinder is offered the other free that day, and taking the offer moves that part", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/promise/simulate");
  await page.getByLabel("Customer", { exact: true }).selectOption("CUS-ECOM");
  await page.getByLabel("Product", { exact: true }).selectOption("MG-500");
  await page.getByLabel("Quantity").fill("3000");
  await page.getByLabel("Wanted on").fill("2026-10-01");
  await page.getByRole("button", { name: "Check availability" }).click();
  const offer = page.getByRole("note", { name: "Substitute" });
  await expect(offer).toContainText("Mixer grinder 750 W can ship 567 of the 902 not on time, on the date asked, from Bhiwandi", { timeout: 45_000 });
  await expect(offer).toContainText(/ordered ₹2,890(\.00)? a unit \(its own price is ₹3,990(\.00)?\)/);
  await expect(offer).toContainText("same base and jars, a stronger motor");

  await page.getByRole("button", { name: "Take this order" }).click();
  const saved = page.locator(".banner.info", { hasText: "Saved" });
  await expect(saved).toContainText(/SO-88222 taken: 3,000 /);
  await expect(page).toHaveURL(/#\/promise\/orders\/SO-88222$/);
  await expect(page.locator("tr", { hasText: "SO-88222" }).first()).toContainText("substitute: 567 Mixer grinder 750 W", { timeout: 45_000 });
  const take = page.getByRole("group", { name: "Substitute Mixer grinder 750 W" });
  await take.getByRole("button", { name: "Ship 567 as Mixer grinder 750 W" }).click();
  await expect(saved).toContainText("SO-88223: 567 Mixer grinder 750 W ship in place of Mixer grinder 500 W at 2,890 a unit, the ordered price; all on the date asked.");
  await expect(saved).toContainText("SO-88222 keeps 2,433");
  await page.goto("/#/promise/orders");
  const line = page.locator("tr", { hasText: "SO-88223" }).first();
  await expect(line).toContainText("in place of SO-88222", { timeout: 45_000 });
  await expect(line).toContainText("on time");
  await expect(page.locator("tr", { hasText: "SO-88222" }).first()).not.toContainText("substitute:");
});
