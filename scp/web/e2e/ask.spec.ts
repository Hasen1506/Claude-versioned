import { expect, test, type Page } from "@playwright/test";

// Enterprise plan 5.2, "Ask the plan": a question in plain words answered from the plan's own records, each sentence
// citing them, with fixes a person tries on a copy and keeps (engine: scp/tower/ask.py).

async function openKaveri(page: Page) {
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await page.goto("/#/tower/ask");
}

async function ask(page: Page, q: string) {
  await page.getByLabel("Ask the plan").fill(q);
  await page.getByRole("button", { name: "Ask", exact: true }).click();
}

const answer = (page: Page) => page.getByRole("region", { name: "The answer" });

test("why late: the answer follows the pegging down to its root, cites the records and offers the inbox's fixes", async ({ page }) => {
  await openKaveri(page);
  await ask(page, "Why is KT-15 late?");
  const a = answer(page);
  await expect(a.getByLabel("Read as")).toHaveText("Read as: Why is Electric kettle 1.5 L (KT-15) late?", { timeout: 45_000 });
  await expect(a.getByRole("status")).toContainText(/units of Electric kettle 1\.5 L \(KT-15\) are projected late/);
  const why = a.getByRole("list", { name: "Why" });
  await expect(why).toContainText(/Forecast of .* for E-commerce marketplaces: 132 of 132/);
  // the first finding's chain is open: the transfer that reaches it late, and why that transfer is late
  const chain = why.locator("details").first();
  await expect(chain.locator("summary")).toContainText(/What holds it up \(\d+ steps?\)/);
  await expect(chain).toContainText(/TO-0001-01 .* is available 2026-09-30, needed 2026-09-28/);
  await expect(chain).toContainText(/TO-0001-01 should have started/);
  // each record cited opens where it is seen
  const cite = chain.locator("a.cite", { hasText: "TO-0001-01" }).first();
  await expect(cite).toHaveAttribute("href", "#/plan/orders/TO-0001-01");
  // the inbox's fixes for what the chain reaches are offered; tried on a copy, this one says it does not help
  const todo = page.locator("section.panel", { hasText: "What to do about it" });
  await todo.getByRole("button", { name: /^Try it: / }).first().click();
  const out = todo.getByRole("region", { name: "What this change does" });
  await expect(out).toContainText("Tried on a copy of the plan", { timeout: 45_000 });
  await expect(out).toContainText(/stays late|does not lower/);
  await out.getByRole("button", { name: "Leave it" }).click();
  await expect(out).toHaveCount(0);
});

test("a fix that works is kept as one change, and the question asked again on the changed data", async ({ page }) => {
  await openKaveri(page);
  await ask(page, "Why is PUNE-WIND overloaded?");
  const a = answer(page);
  await expect(a.getByRole("status")).toHaveText("PUNE-WIND is over its capacity and overtime on 7 more days in periods with room.", { timeout: 45_000 });
  await expect(a.getByRole("list", { name: "Why" }).locator("li").first()).toContainText(/h of work on .* h with overtime; most from MO-/);
  const todo = page.locator("section.panel", { hasText: "What to do about it" });
  await todo.getByRole("button", { name: /^Try it: Add .* of overtime/ }).click();
  const out = todo.getByRole("region", { name: "What this change does" });
  await expect(out.locator(".tile", { hasText: "This problem" })).toContainText(/→ gone/, { timeout: 45_000 });
  await out.getByRole("button", { name: "Keep this change" }).click();
  await expect(a.getByRole("status")).toHaveText(/^PUNE-WIND is not over its capacity on any day/, { timeout: 45_000 });
  const undo = page.getByRole("button", { name: "Undo", exact: true });
  await expect(undo).toBeEnabled();
  await undo.click();
  await expect(undo).toBeDisabled();
});

test("what if: the change is planned on a copy, its effect shown, and it is kept as a scenario", async ({ page }) => {
  await openKaveri(page);
  await ask(page, "What if Hindalco copper is out?");
  const a = answer(page);
  await expect(a.getByLabel("Read as")).toHaveText("Read as: What if: SUP-COPPER out?", { timeout: 60_000 });
  await expect(a.getByRole("status")).toContainText(/^With SUP-COPPER out: .* on time\), cost/);
  await expect(a.getByRole("list", { name: "Why" })).toContainText(/^Service: .*%/);
  await page.getByRole("button", { name: "Keep as a scenario" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Kept as the scenario" })).toContainText("SUP-COPPER out", { timeout: 30_000 });
});

test("who owns and what is at risk come from the worklist; a question it cannot read offers ones it can", async ({ page }) => {
  await openKaveri(page);
  await page.getByRole("button", { name: "What is at risk?" }).click();
  const a = answer(page);
  await expect(a.getByRole("status")).toContainText(/INR is at risk across \d+ open problems/, { timeout: 45_000 });
  await expect(a.getByRole("list", { name: "Why" }).locator("li").first()).toContainText(/owner /);
  await ask(page, "Who owns KT-15?");
  await expect(a.getByLabel("Read as")).toHaveText("Read as: Who owns the problems on Electric kettle 1.5 L (KT-15)?", { timeout: 45_000 });
  await expect(a.getByRole("status")).toContainText("Rahul Mehta (distribution) owns the most");
  await expect(a.getByRole("list", { name: "Why" })).toContainText("Anything no rule matches goes to");
  await ask(page, "tell me a joke");
  await expect(a.getByRole("status")).toContainText("I can answer why something is late", { timeout: 45_000 });
  const tries = page.getByRole("group", { name: "Questions to try" }).or(page.getByLabel("Questions to try"));
  await expect(tries.getByRole("button", { name: /^Why is .* late for .*\?$/ })).toBeVisible();
});
