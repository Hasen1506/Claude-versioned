import { expect, test, type Page } from "@playwright/test";

async function blank(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Start with an empty company" }).click();
  await page.getByLabel("Company name").fill("Setup regression");
  await page.getByRole("button", { name: "Create the company" }).click();
  await expect(page.getByRole("heading", { name: "Set up your company" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Plan everything", exact: true })).toBeEnabled();
}

async function product(page: Page, price = "250") {
  await page.goto("/#/setup/products");
  await page.getByPlaceholder("e.g. Oil filter").fill("Coffee pack");
  await page.getByLabel("Selling price", { exact: true }).fill(price);
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByLabel("Selling price of Coffee pack")).toHaveValue(price);
}

test("guided product fields follow undo and redo without leaving the page", async ({ page }) => {
  await blank(page);
  await product(page);
  for (const [label, initial, changed] of [
    ["Selling price of Coffee pack", "250", "300"],
    ["Product group of Coffee pack", "", "Drinks"],
    ["Shelf life of Coffee pack in days", "", "14"],
    ["Cost of Coffee pack", "", "90"],
  ]) {
    const input = page.getByLabel(label);
    await input.fill(changed);
    await input.press("Tab");
    await expect(input).toHaveValue(changed);
    await page.getByRole("button", { name: "Undo", exact: true }).click();
    await expect(input).toHaveValue(initial);
    await page.getByRole("button", { name: "Redo", exact: true }).click();
    await expect(input).toHaveValue(changed);
  }
});

test("guided product creation rejects invalid numbers rather than changing their meaning", async ({ page }) => {
  await blank(page);
  await page.goto("/#/setup/products");
  await page.getByPlaceholder("e.g. Oil filter").fill("Coffee pack");
  await page.getByLabel("Selling price", { exact: true }).fill("-10");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Selling price must be 0 or more");
  await expect(page.getByLabel("Selling price of Coffee pack")).toHaveCount(0);
  await page.getByLabel("Selling price", { exact: true }).fill("0");
  await page.getByLabel("Shelf life in days", { exact: true }).fill("1.5");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("whole number of days");
  await expect(page.getByLabel("Selling price of Coffee pack")).toHaveCount(0);
  await page.getByLabel("Shelf life in days", { exact: true }).fill("2");
  await page.getByRole("button", { name: "Add product", exact: true }).click();
  await expect(page.getByLabel("Selling price of Coffee pack")).toHaveValue("0");
  await expect(page.getByLabel("Shelf life of Coffee pack in days")).toHaveValue("2");
});

test("zero prices and costs survive guided edits; invalid inline values leave saved data intact", async ({ page }) => {
  await blank(page);
  await product(page, "0");
  const cost = page.getByLabel("Cost of Coffee pack");
  await cost.fill("0");
  await cost.press("Tab");
  const price = page.getByLabel("Selling price of Coffee pack");
  await price.fill("-3");
  await price.press("Tab");
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(price).toHaveValue("0");
  const life = page.getByLabel("Shelf life of Coffee pack in days");
  await life.fill("1.5");
  await life.press("Tab");
  await expect(life).toHaveValue("");
  await page.goto("/#/data/products/COFFEE-PACK");
  await expect(page.locator("#price")).toHaveValue("0");
  await expect(page.locator("#standard_cost")).toHaveValue("0");
  await expect(page.locator("#shelf_life_days")).toHaveValue("");
});

test("guided route and stock quantities follow undo, redo and validation", async ({ page }) => {
  await blank(page);
  await page.goto("/#/setup/network");
  for (const name of ["Plant A", "Plant B"]) {
    await page.getByPlaceholder("e.g. Pune plant").fill(name);
    await page.getByRole("button", { name: "Add place", exact: true }).click();
  }
  await page.getByLabel("Route from").selectOption("PLANT-A");
  await page.getByLabel("Route to").selectOption("PLANT-B");
  await page.getByLabel("Days in transit", { exact: true }).fill("2");   // no silent default any more (roadmap C)
  await page.getByRole("button", { name: "Add route", exact: true }).click();
  const days = page.getByLabel("Days from Plant A to Plant B");
  await days.fill("4");
  await days.press("Tab");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(days).toHaveValue("2");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(days).toHaveValue("4");
  await days.fill("-1");
  await days.press("Tab");
  await expect(days).toHaveValue("4");
  await expect(page.getByRole("alert")).toBeVisible();
  await product(page);
  await page.goto("/#/setup/product/COFFEE-PACK/PLANT-A");
  const stock = page.getByLabel("On hand of Coffee pack at Plant A");
  await stock.fill("50");
  await stock.press("Tab");
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(stock).toHaveValue("0");
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(stock).toHaveValue("50");
  await stock.fill("-1");
  await stock.press("Tab");
  await expect(stock).toHaveValue("50");
  await expect(page.getByRole("alert")).toBeVisible();
});
