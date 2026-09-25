import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    // a 422 is the engine's typed rejection of invalid values: handled by the UI, not an error
    if (m.type() === "error" && !m.text().includes("status of 422")) errors.push(m.text());
  });
  (page as unknown as { __errors: string[] }).__errors = errors;
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

test("golden path: example → readiness → plan → drill-down → edit → stale → re-plan", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();

  // network map renders every location and traces a product
  await expect(page.locator(".net .node")).toHaveCount(12);
  await page.selectOption('select[aria-label="Trace product"]', "KT-15");
  await expect(page.locator(".net .node.dim").first()).toBeVisible();
  await page.locator(".net .node", { hasText: "PLT-PUNE" }).click();
  await expect(page.getByText("Products planned here")).toBeVisible();

  // readiness passes
  await page.getByRole("link", { name: /Readiness/ }).click();
  await expect(page.getByText("Ready to plan")).toBeVisible();

  // plan
  await page.getByRole("button", { name: "Run plan" }).first().click();
  await expect(page.getByText("Total plan cost")).toBeVisible();
  await expect(page.getByText("Plan current")).toBeVisible();
  await expect(page.locator(".tile .value").nth(1)).toContainText("%");

  // node drill-down and pegging
  await page.goto("/#/plan/node/DC-DELHI/MG-750");
  await expect(page.getByText("Stock / requirements by bucket")).toBeVisible();
  await page.locator("tr.clickable", { hasText: "TO-" }).first().click();
  await expect(page.getByRole("heading", { name: "Serves" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Depends on" })).toBeVisible();

  // capacity
  await page.goto("/#/plan/capacity/PUNE-L1");
  await expect(page.getByText("Load by bucket")).toBeVisible();

  // edit an input → plan becomes stale → re-plan → current again
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  const onHand = page.locator('input[id="on_hand"]');
  await onHand.fill("20000");
  await onHand.press("Enter");
  await expect(page.getByText("Plan stale")).toBeVisible();
  await page.getByRole("button", { name: "Run plan" }).click();
  await expect(page.getByText("Plan current")).toBeVisible();

  // undo restores the previous value
  await page.goto("/#/data/location_products/PLT-PUNE%7CRM-HEATER");
  await page.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator('input[id="on_hand"]')).toHaveValue("14000");
});

test("typed inputs: a percent typed as a fraction is rejected with the field named", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Single-product bottler").click();
  await expect(page.locator(".net .node")).toHaveCount(3);
  await page.goto("/#/settings");
  const wacc = page.locator('input[id="wacc"]');
  await expect(wacc).toHaveValue("12"); // shown as percent, stored as 0.12
  await wacc.fill("1200");
  await wacc.press("Enter");
  await expect(page.getByText("Invalid values")).toBeVisible();
  await page.goto("/#/readiness");
  await expect(page.getByText("settings › wacc")).toBeVisible();
  await page.goto("/#/settings");
  await page.locator('input[id="wacc"]').fill("12");
  await page.locator('input[id="wacc"]').press("Enter");
  await expect(page.getByText("Invalid values")).toHaveCount(0);
});

test("blank network: readiness guides the first steps", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Create blank network" }).click();
  await expect(page.getByRole("heading", { name: "Locations", exact: true })).toBeVisible();
  await page.getByRole("button", { name: /New location/ }).click();
  await expect(page.locator('input[id="id"]')).toHaveValue(/L-\d+/);
  await page.goto("/#/network");
  await expect(page.locator(".net .node")).toHaveCount(1);
});
