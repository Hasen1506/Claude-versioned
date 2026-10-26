import { expect, test } from "@playwright/test";

// Enterprise 8.3, demand planning D13 (CONFORMANCE §2), used the guide's way on Kaveri. Input: the mixer grinder family,
// six series (500 W and 750 W to e-commerce, North and West trade), 2,080 forecast for the week of 28 September.
// Processing: the planners expect a trade scheme to lift the family to 2,500 that week and type the family's total
// once, in the consensus grid. Output: the 2,500 is spread over the six series by their own forecast (×1.202, whole
// units that add up: West trade's 500 W 605 → 727), each says why, and the family row reads 2,500.
test("a family's total typed once is spread over its series", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/demand/consensus");
  const families = page.getByRole("table", { name: "By product family" });
  const cell = families.getByLabel("Mixer grinders, Mon 28 Sep");
  await expect(cell).toHaveAttribute("placeholder", "2,080", { timeout: 45_000 });
  await expect(families.getByRole("row", { name: /Mixer grinders/ })).toContainText("6 series");

  await cell.fill("2500");
  await cell.press("Enter");
  const west = page.getByLabel("Mixer grinder 500 W at West trade distributors, Mon 28 Sep");
  await expect(west).toHaveAttribute("placeholder", "727", { timeout: 45_000 });
  await expect(page.getByLabel("Mixer grinder 750 W at E-commerce marketplaces, Mon 28 Sep")).toHaveAttribute("placeholder", "294");
  await expect(families.getByLabel("Mixer grinders, Mon 28 Sep")).toHaveValue("2500");
  await expect(west.locator("xpath=..")).toHaveAttribute("title", /Mixer grinders family: Consensus grid/);
  // the kettles are another family: untouched
  await expect(families.getByLabel("Kettles, Mon 28 Sep")).toHaveAttribute("placeholder", "1,048");
});
