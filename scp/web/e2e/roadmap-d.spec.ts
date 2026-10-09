import { expect, test, type Page } from "@playwright/test";

// Roadmap D (UX audit of 7 Oct 2026, section 4): the browser's session is an HttpOnly cookie with a double-submit
// CSRF token, a token kept in the browser before the change is swapped for the cookie once, and new passwords follow
// the policy (length, breached list, not the e-mail).

const STRONG = "kaveri-pumps-chennai-2026";

async function makeAccount(page: Page, email: string, password = STRONG) {
  await page.goto("/#/account");
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Your name").fill("Roadmap D");
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Make the account" }).click();
}

test("signing in keeps the session in an HttpOnly cookie, never in the browser's storage", async ({ page }) => {
  const email = `cookie-${Date.now()}@kaveri.in`;
  await page.goto("/");
  await page.getByText("Kaveri Kitchenware").click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  const answer = page.waitForResponse((r) => r.url().endsWith("/api/auth/signup"));
  await makeAccount(page, email);
  expect((await (await answer).json()).token).toBe("");  // the page never sees the session (it is in the cookie)
  await expect(page.getByText(/^Signed in as/)).toBeVisible();
  const kept = await page.evaluate(() => JSON.parse(localStorage.getItem("scp.session.v1") ?? "{}"));
  expect(kept.token).toMatch(/^cookie:/);                // a marker, not a token that signs in
  const cookies = await page.context().cookies();
  const session = cookies.find((c) => c.name === "scp_session")!;
  expect(session.httpOnly).toBe(true);
  expect(session.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain("scp_session");   // the page cannot read it
  // and it works: the server knows who this is, and a change from the page goes through (CSRF token sent)
  expect((await (await page.request.get("/api/auth/me")).json()).user.email).toBe(email);
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText(/^Saved/);
});

test("a sign-in asking for the cookie without this browser's CSRF token is refused (login CSRF)", async ({ page }) => {
  await page.goto("/");
  const forged = await page.request.post("/api/auth/signup", { headers: { "X-SCP-Session": "cookie" },
    data: { email: `forged-${Date.now()}@kaveri.in`, password: STRONG } });
  expect(forged.status()).toBe(403);
  expect((await page.context().cookies()).find((c) => c.name === "scp_session")).toBeUndefined();
});

test("a change made with the cookie but without the CSRF token is refused", async ({ page }) => {
  await makeAccount(page, `csrf-${Date.now()}@kaveri.in`);
  await expect(page.getByText(/^Signed in as/)).toBeVisible();
  const example = await (await page.request.get("/api/examples/single_product_plant")).json();
  const forged = await page.request.post("/api/companies", { data: { dataset: example } });
  expect(forged.status()).toBe(403);
  expect((await forged.json()).detail).toContain("X-CSRF-Token");
  const csrf = (await page.context().cookies()).find((c) => c.name === "scp_csrf")!.value;
  expect((await page.request.post("/api/companies", { headers: { "X-CSRF-Token": csrf }, data: { dataset: example } })).ok()).toBe(true);
});

test("a token kept in the browser before the change is swapped for the cookie once, and stops working", async ({ page }) => {
  const email = `legacy-${Date.now()}@kaveri.in`;
  // an account whose sign-in (made the old way) left its token in this browser's storage
  const s = await (await page.request.post("/api/auth/signup", { data: { email, name: "Legacy", password: STRONG } })).json();
  await page.goto("/");
  await page.evaluate((v) => localStorage.setItem("scp.session.v1", JSON.stringify(v)), { token: s.token, user: s.user });
  await page.reload();
  await expect.poll(async () => page.evaluate(() => JSON.parse(localStorage.getItem("scp.session.v1") ?? "{}").token ?? "")).toMatch(/^cookie:/);
  expect((await page.context().cookies()).find((c) => c.name === "scp_session")?.httpOnly).toBe(true);
  await page.goto("/#/account");
  await expect(page.getByText(/^Signed in as Legacy/)).toBeVisible();
  // the old token is worth nothing now
  expect((await page.request.get("/api/auth/me", { headers: { Authorization: `Bearer ${s.token}` } })).status()).toBe(401);
});

test("a new password must pass the policy: long enough and not a breached one", async ({ page }) => {
  await makeAccount(page, `weak-${Date.now()}@kaveri.in`, "password1234");
  await expect(page.getByRole("alert")).toContainText("breached");
  await expect(page.getByText(/at least 12 characters/)).toBeVisible();
  await page.getByLabel(/^Password/).fill(STRONG);
  await page.getByRole("button", { name: "Make the account" }).click();
  await expect(page.getByText(/^Signed in as/)).toBeVisible();
});
