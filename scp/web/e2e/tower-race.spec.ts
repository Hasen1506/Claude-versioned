import { expect, test } from "@playwright/test";

// The CI failure on the control tower: an owner typed and "Seen" clicked straight after are two changes. The server
// takes the owner first and its answer is held back here so it comes last; the acknowledgement must still stand, and so must the owner.

test("an owner typed and Seen clicked straight after both stand, whichever answer comes last", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/tower");
  await page.getByRole("button", { name: "Recalculate", exact: true }).click();
  await page.getByRole("tab", { name: /Problems/ }).click();
  await page.getByRole("radio", { name: "By owner and age" }).click();
  await page.route("**/api/tower/items/**", async (route) => {
    if (!(route.request().postData() ?? "").includes('"owner"')) return route.continue();
    const answer = await route.fetch();          // the server takes the owner first; its answer comes back last
    await new Promise((r) => setTimeout(r, 1500));
    await route.fulfill({ response: answer });
  });
  const owner = page.getByLabel(/^Owner of DEMAND_AT_RISK/).first();
  await owner.fill("Asha Kulkarni");
  await owner.press("Enter");
  await page.getByRole("button", { name: /^Acknowledge DEMAND_AT_RISK/ }).first().click();
  await expect(page.locator(".tile", { hasText: "Acknowledged" }).locator(".value")).toHaveText("1", { timeout: 10_000 });
  await page.waitForTimeout(2500);
  await expect(page.locator(".tile", { hasText: "Acknowledged" }).locator(".value")).toHaveText("1");
  await expect(page.locator('input[value="Asha Kulkarni"]')).toHaveCount(1);
});
