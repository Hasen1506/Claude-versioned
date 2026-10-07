// Roadmap PR C: defaults that were set without being shown are shown and editable (UX audit, section 2).
import { expect, test, type Page } from "@playwright/test";

async function create(page: Page, fill?: (p: Page) => Promise<void>) {
  await page.goto("/");
  await page.getByRole("button", { name: "Start with an empty company" }).click();
  await page.getByLabel("Company name").fill("Assumptions Co");
  if (fill) await fill(page);
  await page.getByRole("button", { name: "Create the company" }).click();
  await expect(page.getByRole("heading", { name: "Set up your company" })).toBeVisible();
}

test("finance and planning assumptions are shown at creation, saved, and editable afterwards", async ({ page }) => {
  await create(page, async (p) => {
    await expect(p.getByLabel("Cost of capital, % a year")).toHaveValue("12");
    await expect(p.getByLabel("Storage and risk, % a year")).toHaveValue("8");
    await expect(p.getByLabel("Service level, %")).toHaveValue("95");
    await expect(p.getByLabel("Plan ahead, weeks")).toHaveValue("26");
    await p.getByLabel("Cost of capital, % a year").fill("10.5");
    await p.getByLabel("Service level, %").fill("97");
    await p.getByLabel("Plan ahead, weeks").fill("13");
    await p.getByLabel("Time zone").fill("Asia/Kolkata");
    await p.getByRole("button", { name: /Service level by ABC-XYZ class/ }).click();
    await expect(p.getByLabel("Service level CZ")).toHaveValue("90");
    await p.getByLabel("Service level AX").fill("99");
  });
  await page.goto("/#/setup/company");
  await expect(page.getByLabel("Cost of capital, % a year")).toHaveValue("10.5");
  await expect(page.getByLabel("Service level, %")).toHaveValue("97");
  await expect(page.getByLabel("Plan ahead, weeks")).toHaveValue("13");
  await expect(page.getByLabel("Time zone")).toHaveValue("Asia/Kolkata");
  await page.getByRole("button", { name: /Service level by ABC-XYZ class/ }).click();
  await expect(page.getByLabel("Service level AX")).toHaveValue("99");
  // edit afterwards, and refuse an impossible value
  await page.getByLabel("Storage and risk, % a year").fill("120");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("storage and risk cost is a percentage");
  await page.getByLabel("Storage and risk, % a year").fill("6");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.reload();
  await expect(page.getByLabel("Storage and risk, % a year")).toHaveValue("6");
});

test("a route has no silent transit time, and fixed batches have no silent size", async ({ page }) => {
  await create(page);
  await page.goto("/#/setup/network");
  for (const name of ["Plant A", "Depot B"]) {
    await page.getByPlaceholder("e.g. Pune plant").fill(name);
    await page.getByRole("button", { name: "Add place", exact: true }).click();
  }
  await page.getByLabel("Route from").selectOption("PLANT-A");
  await page.getByLabel("Route to").selectOption("DEPOT-B");
  await expect(page.getByLabel("Days in transit", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Add route", exact: true }).click();
  await expect(page.getByText("Enter the days in transit")).toBeVisible();
  await expect(page.getByLabel("Days from Plant A to Depot B")).toHaveCount(0);
  await page.getByLabel("Days in transit", { exact: true }).fill("3");
  await page.getByRole("button", { name: "Add route", exact: true }).click();
  await expect(page.getByLabel("Days from Plant A to Depot B")).toHaveValue("3");

  await page.goto("/#/setup/products");
  await page.getByPlaceholder("e.g. Oil filter").fill("Pump");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await page.goto("/#/setup/product/PUMP/PLANT-A");
  await page.getByLabel("Each order covers").last().selectOption("FIXED");
  const batch = page.getByLabel("Batch size", { exact: true });
  await expect(batch).toHaveValue("");
  await batch.fill("40");
  await batch.press("Tab");
  await page.reload();
  await expect(page.getByLabel("Batch size", { exact: true })).toHaveValue("40");
  await page.getByLabel("Safety stock", { exact: true }).selectOption("days_of_supply");
  await expect(page.getByLabel("Days of cover")).toHaveValue("");
});
