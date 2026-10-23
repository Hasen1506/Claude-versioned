import { expect, test } from "@playwright/test";

// Enterprise 8.3, buying B18 and B21 (CONFORMANCE §4), used the guide's way on Kaveri. Input: the closed purchase orders
// of the last year, the open orders and the plan's requisitions, priced at each source's price. Processing: spend per
// supplier and per bought product, each supplier's class, and the sources each product has. Output: every one of the
// nine bought parts has a single source (all the spend); the copper wire supplier takes 31.7 %; the Shenzhen
// supplier is the only source of the heater and the switch, 14 days away and on time three times in four.
test("where the buying money goes and which parts have one supplier", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/buying/spend");
  const single = page.locator(".tile", { hasText: "Bought from one source" });
  await expect(single.locator(".value")).toHaveText("9 of 9", { timeout: 45_000 });
  await expect(single).toContainText("100% of the spend");
  await expect(page.locator(".tile", { hasText: "Biggest supplier" })).toContainText("32%");
  await expect(page.locator(".tile", { hasText: "Biggest supplier" })).toContainText("Hindalco copper (Silvassa)");
  const bySupplier = page.getByRole("table", { name: "Spend by supplier" });
  await expect(bySupplier.getByRole("row").nth(1)).toContainText("Hindalco copper (Silvassa)");
  await expect(bySupplier.getByRole("row").nth(1)).toContainText("31.7%");
  const shenzhen = bySupplier.getByRole("row", { name: /Shenzhen electro-components/ });
  await expect(shenzhen).toContainText("2 of 2");
  await expect(shenzhen).toContainText("75%");
  const heater = page.getByRole("table", { name: "Sourcing" }).getByRole("row", { name: /Concealed heating element/ });
  await expect(heater).toContainText("one");
  await expect(heater).toContainText("Shenzhen electro-components");
  await expect(heater).toContainText("14 d");
});
