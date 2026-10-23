import { expect, test } from "@playwright/test";

// Enterprise 8.3, money F15 (CONFORMANCE §8), used the guide's way on Kaveri. Input: the plan, the open orders and
// forecast at the customers' prices, what was shipped and not billed, and everyone's payment terms. Processing: the
// cash that comes in and goes out week by week. Output: four weeks of production and transfers are paid before the
// first customer pays: the plan needs ₹20.9 lakh on top of the bank by the week of 19 Oct; from 26 Oct it pays its way.
test("the cash the plan needs, week by week, on everyone's payment terms", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/finance/cash");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  const need = page.locator(".tile", { hasText: "Most cash needed" });
  await expect(need).toContainText(/₹20\.9\d?\s*L/, { timeout: 45_000 });
  await expect(need).toContainText("in the week of Mon 19 Oct");
  const weeks = page.getByRole("table", { name: "Cash by week" });
  await expect(weeks.locator("tbody tr")).toHaveCount(26);
  await expect(weeks.locator("tbody tr").first()).toContainText("out: production");
  const paid = weeks.getByRole("row", { name: /^Mon 26 Oct/ });
  await expect(paid).toContainText("in: delivered, to bill");
  await expect(paid).toContainText("forecast");
});
