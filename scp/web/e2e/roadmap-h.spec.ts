// Roadmap PR H: the DMSC example case (a Chennai pump maker and the north-east monsoon) opens from the start screen,
// is labelled as an example case and never as real company data, and brings its own what-if scenarios.
import { expect, test } from "@playwright/test";

test("the Chennai port case opens from the start screen, labelled, and its monsoon scenarios compare in one click", async ({ page }) => {
  await page.goto("/");
  const card = page.getByRole("button", { name: /Example case: Coromandel Pumps, Chennai \(fictional\)/ });
  await expect(card).toBeVisible();
  await expect(card).toContainText("Example case");
  await expect(card).toContainText("not real company data");
  await card.click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });

  await page.goto("/#/whatif");
  await expect(page.getByText("DMSC case: a Chennai pump maker and the north-east monsoon")).toBeVisible();
  await expect(page.locator("main")).toContainText("not real company data");
  await page.getByRole("button", { name: "Load the case's scenarios" }).click();
  await expect(page.getByLabel("Chips of Monsoon at the port")).toContainText("Routes via PORT-MAA +6 d");
  await expect(page.getByLabel("Chips of Monsoon at the port")).toContainText("Lead time +10 d at SUP-SEAL-IMPORT");
  await expect(page.getByLabel("Chips of Monsoon + third shift")).toContainText("Add a shift on ASM-LINE");

  await page.getByRole("button", { name: "Compare side by side" }).click();
  const table = page.getByRole("table", { name: "What-if comparison" });
  await expect(table).toBeVisible({ timeout: 60_000 });
  await expect(table.locator("thead th").nth(1)).toContainText("best service");
  await expect(table.getByRole("row", { name: /On-time service/ })).toContainText("pts");
});

test("an ordinary example is not called a case and offers no case scenarios", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: /Kaveri Kitchenware/ })).not.toContainText("Example case");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/whatif");
  await expect(page.getByRole("heading", { name: "What if… side by side" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Load the case's scenarios" })).toHaveCount(0);
});
