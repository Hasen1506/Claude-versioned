import { expect, test } from "@playwright/test";

test("proof: run every scenario, read a derivation, open a scenario's data in the app", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));

  // reachable before any dataset is open
  await page.goto("/");
  await page.getByRole("link", { name: "See the proof" }).click();
  await expect(page.locator("table.cov tbody tr")).toHaveCount(9);   // eight hand-worked, one generated

  await page.getByRole("button", { name: /Run all/ }).click();
  await expect(page.locator("table.cov .badge.ok")).toHaveCount(9, { timeout: 90_000 });
  await expect(page.locator(".stage-head .badge.ok")).toContainText("checkpoints hold");
  await expect(page.locator("table.cov .badge.error")).toHaveCount(0);

  // a scenario's steps: each checkpoint with the hand-worked value, the engine's, and the arithmetic
  await page.locator("table.cov a", { hasText: "Harbour Paints" }).click();
  await expect(page.getByText("What it caught (7)")).toBeVisible();
  const ss = page.locator("table.checks tr", { hasText: "single-echelon SS" });
  await expect(ss).toContainText("22.613");
  await expect(ss.locator(".why")).toContainText("1.645");
  await page.getByRole("button", { name: "Failures only" }).click();
  await expect(page.getByText("Nothing failed.")).toBeVisible();

  // follow it by hand
  await page.getByRole("button", { name: "Open starting data" }).click();
  await expect(page).toHaveURL(/#\/readiness$/);
  await expect(page.locator(".company")).toHaveText("Harbour Paints");
  expect(errors).toEqual([]);
});
