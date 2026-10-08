import { expect, test, type Browser, type Page } from "@playwright/test";

// Ground-truth flows not covered elsewhere (PR "Property-based and differential test suite"): accepting an invitation,
// resetting a password by mail, a new customer order's validation (ORDER-NEW-01/02), a reload keeping tabs and badges
// (REFRESH-01/02), Back not dropping an edit (BACK-01), a viewer's read-only company, and per-screen undo (UNDO-02).
//
// Deterministic by construction: every address is fixed and unique to its test (the servers start empty for each run),
// mail is found by its recipient (never by position in the shared mail sink), the browser's clock is fixed, nothing
// leaves 127.0.0.1, and every wait is on a visible outcome, never on time.

const MAIL = "http://127.0.0.1:8766";          // the second server of playwright.config.ts: it sends mail to the sink
const SINK = "http://127.0.0.1:2526/messages";
type Taken = { to: string[]; subject: string; text: string };
/** Part of every address: the servers live for the whole run, so a repeat or a retry of a test gets addresses of its
 *  own and never meets the accounts an earlier attempt made. */
const R = () => `-${test.info().repeatEachIndex}-${test.info().retry}`;

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  // 4xx answers are refusals the page shows in words (a used invitation, a wrong password): not errors of the page
  page.on("console", (m) => { if (m.type() === "error" && !/status of 4\d\d/.test(m.text())) errors.push(m.text()); });
  (page as unknown as { __errors: string[] }).__errors = errors;
  await isolate(page);
});

test.afterEach(async ({ page }) => {
  expect((page as unknown as { __errors: string[] }).__errors).toEqual([]);
});

/** No network beyond this machine, and a fixed clock (dates shown never depend on when the test runs). */
async function isolate(page: Page) {
  await page.context().route((u) => !["127.0.0.1", "localhost"].includes(u.hostname), (r) => r.abort());
  await page.clock.setFixedTime(new Date("2026-10-07T09:00:00Z"));
}

async function newPage(browser: Browser): Promise<Page> {
  const p = await (await browser.newContext()).newPage();
  p.on("dialog", (d) => d.accept());
  await isolate(p);
  return p;
}

async function openExample(page: Page, name = "Kaveri Kitchenware") {
  await page.goto("/");
  await page.getByText(name).click();
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
}

async function makeAccount(page: Page, email: string, name: string, password = "ground-truth-1") {
  await page.getByRole("tab", { name: "Make an account" }).click();
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Your name").fill(name);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByRole("button", { name: "Make the account" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** Open the example, make the owner's account and keep the company on the server. */
async function ownCompany(page: Page, email: string) {
  page.on("dialog", (d) => d.accept());
  await openExample(page);
  await page.locator(".save-chip .save-long").click();
  await makeAccount(page, email, "Owner " + email.split("@")[0]);
  await page.getByRole("button", { name: "Keep it on the server" }).click();
  await expect(page.locator(".save-chip .save-long")).toHaveText("Saved");
}

async function invite(page: Page, email: string, role: "planner" | "viewer"): Promise<string> {
  await page.getByLabel("Colleague's e-mail").fill(email);
  await page.getByLabel("Their role").selectOption(role);
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.locator("tr", { hasText: email })).toContainText("invited");
  return (await page.getByLabel("Invitation link").inputValue()).replace(/^https?:\/\/[^/]+/, "");
}

/** The mail the sink took for ``to`` whose subject matches, once it has arrived. */
async function mailFor(page: Page, to: string, subject: RegExp): Promise<Taken> {
  let got: Taken | undefined;
  await expect.poll(async () => {
    const all = (await (await page.request.get(SINK)).json()) as Taken[];
    got = all.filter((m) => m.to.includes(to) && subject.test(m.subject)).pop();
    return !!got;
  }, { timeout: 15_000 }).toBe(true);
  return got!;
}

/** Wait until the undo steps are kept in the browser (written a moment after the last change, so a reload brings them
 *  back): a wait on the outcome, never on time. Opening never creates the database (that is the app's to make). */
async function undoKept(page: Page) {
  await expect.poll(() => page.evaluate(() => new Promise<number>((done) => {
    const r = indexedDB.open("scp");
    r.onupgradeneeded = () => r.transaction?.abort();
    r.onerror = () => done(0);
    r.onsuccess = () => {
      const db = r.result;
      if (!db.objectStoreNames.contains("undo")) { db.close(); done(0); return; }
      const g = db.transaction("undo").objectStore("undo").get("steps");
      g.onsuccess = () => { db.close(); done((g.result as { past?: unknown[] } | undefined)?.past?.length ?? 0); };
      g.onerror = () => { db.close(); done(0); };
    };
  })), { timeout: 15_000 }).toBeGreaterThan(0);
}

// ---- invitations ----------------------------------------------------------------------------------------------------
test("an invitation is accepted by the invited address only, once; the new member opens the company with the role given", async ({ page, browser }) => {
  await ownCompany(page, `owner@gt-invite${R()}.example`);
  const link = await invite(page, `new.planner@gt-invite${R()}.example`, "planner");

  // the invitee opens the link signed out: told to sign in or make an account with that address, on the same page
  const b = await newPage(browser);
  await b.goto(link);
  await expect(b.getByText(/You are invited to a company\. Sign in, or make an account/)).toBeVisible();
  await makeAccount(b, `new.planner@gt-invite${R()}.example`, "New Planner");
  await b.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(b.getByText(/You joined Kaveri Kitchenware/)).toBeVisible();
  await b.goto("/#/account");
  await b.reload();
  await b.getByRole("button", { name: /Open Kaveri Kitchenware/ }).click();
  await expect(b.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  await expect(b.locator(".save-chip .save-long")).toHaveText(/^Saved/);          // a planner: not "View only"

  // the owner sees the member joined, as planner
  await page.reload();
  await expect(page.locator("tr", { hasText: `new.planner@gt-invite${R()}.example` })).toContainText("planner");
  await expect(page.locator("tr", { hasText: `new.planner@gt-invite${R()}.example` })).not.toContainText("invited");

  // the same link a second time, or for anyone else, joins nobody
  await b.goto(link);
  await b.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(b.locator(".banner.error")).toBeVisible();
  const c = await newPage(browser);
  await c.goto("/#/account");
  await makeAccount(c, `someone.else@gt-invite${R()}.example`, "Someone Else");
  const second = await invite(page, `viewer.only@gt-invite${R()}.example`, "viewer");
  await c.goto(second);
  await c.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(c.locator(".banner.error")).toBeVisible();
  await c.goto("/#/account");
  await c.reload();
  await expect(c.getByRole("button", { name: /Open Kaveri Kitchenware/ })).toHaveCount(0);

  // an account whose address is not confirmed is shown no invitation to accept without the link (CV-C01: anyone can
  // register any address); the invitation's own link, opened by that address, still joins it, as viewer
  const d = await newPage(browser);
  await d.goto("/#/account");
  await makeAccount(d, `viewer.only@gt-invite${R()}.example`, "Viewer Only");
  await d.reload();
  await expect(d.getByText("address not confirmed")).toBeVisible();
  await expect(d.getByText(/invited you to Kaveri Kitchenware/)).toHaveCount(0);
  await d.goto(second);
  await d.getByRole("button", { name: "Accept the invitation" }).click();
  await expect(d.getByText(/You joined Kaveri Kitchenware/)).toBeVisible();
  await page.reload();
  await expect(page.locator("tr", { hasText: `viewer.only@gt-invite${R()}.example` })).toContainText("viewer");
  await expect(page.locator("tr", { hasText: `viewer.only@gt-invite${R()}.example` })).not.toContainText("invited");
});

// scp run 37731060982 (main red): the members table read the list once when it opened, and showed that answer whenever
// it came. When the server answered that read before an invitation but the browser delivered it after the invitation's
// own answer, the table went back to the list without the invited person ("invited" row not found). The read's answer
// is held here until the invitation has been answered and shown, then delivered: the invited row must stay.
test("a slow first read of the members never hides a colleague invited meanwhile", async ({ page }) => {
  let deliver!: () => void;
  const late = new Promise<void>((r) => { deliver = r; });
  let reads = 0;
  // count the members answers the page has read (the invitation's, then the late one): a wait on the page having taken
  // the late answer, never on time
  await page.addInitScript(() => {
    const w = window as unknown as { __membersRead: number };
    w.__membersRead = 0;
    const json = Response.prototype.json;
    Response.prototype.json = async function (this: Response) {
      const out = await json.call(this);
      if (/\/members$/.test(this.url)) w.__membersRead += 1;
      return out;
    };
  });
  await page.route(/\/api\/companies\/[^/]+\/members$/, async (route) => {
    if (route.request().method() !== "GET" || reads++ > 0) return route.continue();
    const answered = await route.fetch();          // the server answers now, before the invitation exists
    await late;                                    // ... and the browser gets that answer only after the invitation's
    await route.fulfill({ response: answered });
  });
  await ownCompany(page, `owner@gt-slow-read${R()}.example`);
  const email = `colleague@gt-slow-read${R()}.example`;
  await invite(page, email, "planner");
  await expect.poll(() => reads).toBe(1);          // the first read is the one held
  const delivered = page.waitForResponse((r) => r.request().method() === "GET" && /\/members$/.test(r.url()));
  deliver();
  await (await delivered).finished();
  // the page has read the late answer, and drawn two frames since
  await expect.poll(() => page.evaluate(() => (window as unknown as { __membersRead: number }).__membersRead)).toBe(2);
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done))));
  await expect(page.locator("tr", { hasText: email })).toHaveCount(1);
  await expect(page.locator("tr", { hasText: email })).toContainText("invited");
  // and the server's list agrees after a reload
  await page.unroute(/\/api\/companies\/[^/]+\/members$/);
  await page.reload();
  await expect(page.locator("tr", { hasText: email })).toContainText("invited");
});

// ---- password reset (on the server that sends mail) -----------------------------------------------------------------
test.describe("password reset", () => {
  test.use({ baseURL: MAIL });

  test("a reset link by mail sets a new password once; the old one stops working; an unknown address learns nothing", async ({ page }) => {
    const email = `forgetful@gt-reset${R()}.example`;
    await page.goto("/#/account");
    await makeAccount(page, email, "Forgetful", "old-password-1");
    await page.getByRole("button", { name: "Sign out" }).click();
    // signed out, the form opens on "Sign in": the first account exists now (AUTH-01: it offered to make the first one)
    await expect(page.getByRole("tab", { name: "Sign in" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByText("Nobody has an account on this server yet")).toHaveCount(0);

    // ask for a link: the answer is the same for an address with no account, and only the real one gets mail
    for (const who of [`nobody@gt-reset${R()}.example`, email]) {
      await page.getByRole("button", { name: "Forgot your password?" }).click();
      await page.getByLabel("E-mail").fill(who);
      await page.getByRole("button", { name: "Send me a link" }).click();
      await expect(page.getByRole("status")).toContainText(`If ${who} has an account here, a link to set a new password is on its way`);
      await page.getByRole("button", { name: "Back to signing in" }).click();
    }
    const mail = await mailFor(page, email, /password/i);
    const link = mail.text.match(/https?:\/\/\S+#\/account\/reset\/\S+/)![0];
    const all = (await (await page.request.get(SINK)).json()) as Taken[];
    expect(all.filter((m) => m.to.includes(`nobody@gt-reset${R()}.example`))).toEqual([]);

    // the link: a new password, and signed in with it
    await page.goto(link);
    await expect(page.getByText("Choose a new password")).toBeVisible();
    await page.getByLabel(/New password/).fill("new-password-2");
    await page.getByRole("button", { name: "Set it and sign in" }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    // the old password no longer signs in; the new one does
    await page.getByLabel("E-mail").fill(email);
    await page.getByLabel(/^Password/).fill("old-password-1");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await page.getByLabel(/^Password/).fill("new-password-2");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

    // the link works once
    await page.getByRole("button", { name: "Sign out" }).click();
    await page.goto(link);
    await page.getByLabel(/New password/).fill("third-password-3");
    await page.getByRole("button", { name: "Set it and sign in" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  });
});

// ---- a new customer order: validation (ORDER-NEW-01/02) -------------------------------------------------------------
test("a new order refuses a negative or empty quantity and a priority outside 1–9, warns of a huge quantity or a past date, then takes the order as typed", async ({ page }) => {
  await openExample(page);
  await page.goto("/#/promise/simulate");
  const check = page.getByRole("button", { name: "Check availability" });
  const qtyIn = page.getByLabel("Quantity"), prio = page.getByLabel("Priority");

  await qtyIn.fill("-50");                                            // never turned into 50
  await expect(page.getByRole("alert").filter({ hasText: "The quantity must be more than zero." })).toBeVisible();
  await expect(check).toBeDisabled();
  await expect(qtyIn).toHaveValue("-50");
  await qtyIn.fill("");
  await expect(page.getByRole("alert").filter({ hasText: "Type the quantity ordered" })).toBeVisible();
  await expect(check).toBeDisabled();
  await qtyIn.fill("12");
  await expect(page.getByRole("alert")).toHaveCount(0);

  for (const bad of ["", "0", "12", "2.5", "-1"]) {                   // never turned into 0
    await prio.fill(bad);
    await expect(page.getByRole("alert").filter({ hasText: "The priority is a whole number from 1 (first) to 9." })).toBeVisible();
    await expect(check).toBeDisabled();
  }
  await prio.fill("3");
  await expect(page.getByRole("alert")).toHaveCount(0);

  // warnings: a quantity far above any order of the product, a date before the plan starts; the order can still go
  await qtyIn.fill("90000000");
  await expect(page.getByRole("status").filter({ hasText: "is far more than any order of this product so far" })).toBeVisible();
  const wanted = page.getByLabel("Wanted on");
  const first = await wanted.inputValue();
  const past = new Date(Date.parse(first + "T00:00:00Z") - 40 * 86_400_000).toISOString().slice(0, 10);
  await wanted.fill(past);
  await expect(page.getByRole("status").filter({ hasText: "before the plan starts" })).toBeVisible();
  await expect(check).toBeEnabled();

  // as typed: 12 units, priority 3, on the first date
  await qtyIn.fill("12");
  await wanted.fill(first);
  await expect(page.getByRole("status").filter({ hasText: /far more than|before the plan starts/ })).toHaveCount(0);
  await page.getByLabel("Customer's order number").fill("GT-ORDER-1");
  await check.click();
  await page.getByRole("button", { name: "Take this order" }).click();
  await expect(page.locator(".banner.info", { hasText: "taken" })).toContainText("taken: 12");
  await expect(page).toHaveURL(/#\/promise\/orders\/SO-/);
  await expect(page.getByText(/priority 3/).first()).toBeVisible();
});

test("a multi-line order says which line's quantity is wrong and warns of a past date", async ({ page }) => {
  await openExample(page);
  await page.goto("/#/selling/new");
  await page.getByLabel("Line 10 quantity").fill("-5");
  await expect(page.getByRole("alert").filter({ hasText: "Line 10: the quantity must be more than zero" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Take the order" })).toBeDisabled();
  await page.getByLabel("Line 10 quantity").fill("4");
  const wanted = page.getByLabel("Line 10 wanted on");
  const first = await wanted.inputValue();
  await wanted.fill(new Date(Date.parse(first + "T00:00:00Z") - 40 * 86_400_000).toISOString().slice(0, 10));
  await expect(page.getByRole("status").filter({ hasText: "Line 10: Wanted on" })).toContainText("before the plan starts");
  await expect(page.getByRole("button", { name: "Take the order" })).toBeEnabled();
});

// ---- a reload keeps the page (REFRESH-01/02) ------------------------------------------------------------------------
test("a reload keeps the forecast's workbench and consensus tabs and the performance count in the rail", async ({ page }) => {
  await openExample(page);
  const badge = page.locator('.rail a[href="#/tower"] .rail-count');
  await expect(badge).toBeVisible();
  const before = await badge.textContent();
  await page.goto("/#/demand/consensus");
  await expect(page.getByRole("tab", { name: /Consensus grid/ })).toBeVisible();
  const cells = page.locator("td input.cell");
  await expect(cells.first()).toBeVisible();
  const n = await cells.count();

  await page.reload();
  await expect(page.getByRole("tab", { name: /Series workbench/ })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Consensus grid/ })).toBeVisible();
  await expect(cells).toHaveCount(n, { timeout: 45_000 });             // the grid itself is back, not an empty page
  await expect(badge).toHaveText(before!, { timeout: 45_000 });
  await page.goto("/#/demand/series");
  await expect(page.getByRole("tab", { name: /Series workbench/ })).toHaveAttribute("aria-selected", "true");
});

// ---- Back keeps an edit (BACK-01) -----------------------------------------------------------------------------------
test("Back and Forward keep a value typed into a grid that was never left with Tab or Enter", async ({ page }) => {
  await openExample(page);
  await page.goto("/#/network");
  await page.goto("/#/demand/plan");
  const cell = page.locator("input.dp-in").first();
  await expect(cell).toBeVisible();
  const label = await cell.getAttribute("aria-label");
  await cell.click();
  await cell.fill("4321");                                            // no blur: the planner presses Back straight away
  await page.goBack();
  await expect(page).toHaveURL(/#\/network$/);
  await expect(page.locator(".save-chip .save-long")).toBeVisible();
  await page.goForward();
  await expect(page.getByLabel(label!)).toHaveValue("4321");
  await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();    // it is a change of this screen
  await page.reload();
  await expect(page.getByLabel(label!)).toHaveValue("4321");          // and it was kept, not just shown
});

// ---- a viewer's company is read-only --------------------------------------------------------------------------------
test("a viewer can open and read every page but change nothing, even after a reload", async ({ page, browser }) => {
  await ownCompany(page, `owner@gt-viewer${R()}.example`);
  const link = await invite(page, `reader@gt-viewer${R()}.example`, "viewer");
  const v = await newPage(browser);
  await v.goto(link);
  await makeAccount(v, `reader@gt-viewer${R()}.example`, "Reader");
  await v.getByRole("button", { name: "Accept the invitation" }).click();
  await v.goto("/#/account");
  await v.reload();
  await v.getByRole("button", { name: /Open Kaveri Kitchenware/ }).click();
  await expect(v.getByText(/Everything is up to date/)).toBeVisible({ timeout: 45_000 });
  const chip = v.locator(".save-chip .save-long");
  await expect(chip).toHaveText("View only");

  const readOnly = async () => {
    await v.goto("/#/demand/plan");
    await expect(v.locator("input.dp-in").first()).toBeDisabled();
    await v.goto("/#/data/products");
    await expect(v.getByRole("button", { name: /New product/ })).toBeDisabled();
    await v.goto("/#/promise/simulate");
    await v.getByLabel("Quantity").fill("5");
    await v.getByRole("button", { name: "Check availability" }).click();
    await expect(v.getByRole("button", { name: "Take this order" })).toBeDisabled();
    await v.keyboard.press("Control+z");                              // nothing to undo, nothing changed
    await expect(v.getByRole("button", { name: "Undo" })).toBeDisabled();
    await expect(chip).toHaveText("View only");
  };
  await readOnly();
  await v.reload();
  await readOnly();
  // the owner's company is exactly as it was: the history has no save by the viewer
  await page.goto("/#/history");
  await expect(page.locator("ol.history > li", { hasText: "Reader" }).filter({ hasText: "saved" })).toHaveCount(0);
});

// ---- per-screen undo (UNDO-02) --------------------------------------------------------------------------------------
test("undo acts only on the screen where the change was made, and that survives a reload", async ({ page }) => {
  await openExample(page);
  const undo = page.getByRole("button", { name: "Undo" });

  // a change on the demand plan
  await page.goto("/#/demand/plan");
  const cell = page.locator("input.dp-in").first();
  const label = (await cell.getAttribute("aria-label"))!;
  const was = await cell.inputValue();
  await cell.fill("2468");
  await cell.press("Enter");
  await expect(undo).toBeEnabled();

  // another screen: its Undo does not reach back into the demand plan, and says where the change was
  await page.goto("/#/network");
  await expect(undo).toBeDisabled();
  await expect(undo).toHaveAttribute("title", /The last change was made on .*Demand.*: open it to undo it/);
  await page.keyboard.press("Control+z");
  await page.goto("/#/demand/plan");
  await expect(page.getByLabel(label)).toHaveValue("2468");          // Ctrl+Z elsewhere undid nothing here

  // a reload keeps the step and the screen it belongs to
  await undoKept(page);
  await page.reload();
  await expect(page.getByLabel(label)).toHaveValue("2468");
  await expect(undo).toBeEnabled();
  await page.goto("/#/network");
  await expect(undo).toBeDisabled();
  await page.goto("/#/demand/plan");
  await undo.click();
  await expect(page.getByLabel(label)).toHaveValue(was);
  await expect(undo).toBeDisabled();
});
