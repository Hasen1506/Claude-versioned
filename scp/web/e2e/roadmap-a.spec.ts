// Roadmap PR A: status signals that contradicted each other (UX audit, 7 Oct 2026).
import { expect, test, type Page } from "@playwright/test";

async function importCompany(page: Page, data: object, name: string) {
  await page.goto("/");
  await page.getByRole("button", { name: "Start with an empty company" }).click();
  await page.getByLabel("Company name").fill("Roadmap A");
  await page.getByRole("button", { name: "Create the company" }).click();
  await expect(page.getByRole("heading", { name: "Set up your company" })).toBeVisible();
  await page.getByRole("button", { name: "More", exact: true }).click();
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("menuitem", { name: "Import a dataset file…" }).click();
  await (await chooser).setFiles({ name: "fixture.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(data)) });
  await expect(page.locator(".topbar .company")).toHaveText(name);
}

const sourcedOnly = {
  settings: { company_name: "Sourced only", planning_start: "2026-01-05", horizon_days: 28, default_calendar: "CAL" },
  calendars: [{ id: "CAL", workdays: [0, 1, 2, 3, 4] }],
  locations: [{ id: "P", type: "plant" }, { id: "S", type: "supplier" }],
  products: [{ id: "A", type: "FG" }, { id: "B", type: "RM" }],
  production_sources: [{ id: "PV-A", location: "P", product: "A", fixed_lead_time_workdays: 1, components: [{ product: "B", qty: 1 }] }],
  purchasing_sources: [{ id: "PIR-B", supplier: "S", product: "B", location: "P", price: 5, lead_time_days: 3 }],
};

test("products at places lists every sourced product-place before any plan or policy exists", async ({ page }) => {
  await importCompany(page, sourcedOnly, "Sourced only");
  await page.goto("/#/material");
  await expect(page.getByText("No products at places yet")).toHaveCount(0);
  await expect(page.locator(".content .small.muted", { hasText: /^2 of 2$/ })).toBeVisible();
  await expect(page.locator('a[href="#/material/A/P"]')).toBeVisible();
  await expect(page.locator('a[href="#/material/B/P"]')).toBeVisible();
});

test("the first-run guide ticks a check and a what-if only when they were done, not when their pages were opened", async ({ page }) => {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/promise");
  await page.goto("/#/promise/simulate");
  await page.goto("/#/versions");
  await page.goto("/#/home");
  const step = (t: string) => page.locator(".guide li", { hasText: t });
  await expect(step("Check a new customer order")).not.toHaveClass(/\bdone\b/);
  await expect(step("Try a what-if")).not.toHaveClass(/\bdone\b/);
  await page.goto("/#/promise/simulate");
  await page.locator("select").nth(1).selectOption("MG-750");
  await page.locator('input[type="number"]').first().fill("10");
  await page.getByRole("button", { name: "Check availability" }).click();
  await expect(page.getByRole("button", { name: "Take this order" })).toBeEnabled();
  await page.goto("/#/home");
  await expect(step("Check a new customer order")).toHaveClass(/\bdone\b/);
  await expect(step("Try a what-if")).not.toHaveClass(/\bdone\b/);
});
