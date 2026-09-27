import { expect, test } from "@playwright/test";

type Info = { id: string; company: string; found?: string[] };

test("proof: run every scenario, read a derivation, open a scenario's data in the app", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  // the page lists what the engine registers, so adding a scenario needs no change here
  const infos: Info[] = await (await request.get("/api/scenarios")).json();
  const paints = infos.find((s) => s.company === "Harbour Paints");
  expect(paints).toBeDefined();

  // reachable before any dataset is open
  await page.goto("/");
  await page.getByRole("link", { name: "See the proof" }).click();
  await expect(page.locator("table.cov tbody tr")).toHaveCount(infos.length);

  await page.getByRole("button", { name: /Run all/ }).click();
  await expect(page.locator("table.cov .badge.ok")).toHaveCount(infos.length, { timeout: 90_000 });
  await expect(page.locator(".stage-head .badge.ok")).toContainText("checkpoints hold");
  await expect(page.locator("table.cov .badge.error")).toHaveCount(0);

  // a scenario's steps: each checkpoint with the hand-worked value, the engine's, and the arithmetic
  await page.locator("table.cov a", { hasText: "Harbour Paints" }).click();
  await expect(page.getByText(`What it caught (${paints!.found?.length ?? 0})`)).toBeVisible();
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
