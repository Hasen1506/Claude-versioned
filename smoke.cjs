// Browser smoke: load app_v2 in real Chromium, click through all 13 tabs, assert
// each renders without an ErrorBoundary card / pageerror / console error, then
// exercise the new Solver Anatomy Lab (view source + live solve) on Console.
const { chromium } = require('playwright');
const BASE = 'http://localhost:5000/';
const STAGES = ['home','setup','products','network','demand','plan','production',
                'sourcing','logistics','finance','console','scenarios','reference'];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const results = [];
  let curErrors = [];
  page.on('console', m => { if (m.type() === 'error') curErrors.push('console: ' + m.text().slice(0,200)); });
  page.on('pageerror', e => curErrors.push('pageerror: ' + (e.message||String(e)).slice(0,200)));

  // wait until babel-standalone has compiled every script and the chrome mounted
  const waitMounted = async () => {
    await page.waitForFunction(() => {
      const t = document.body && document.body.innerText || '';
      return t.includes('SUPPLY-CHAIN OS') || t.length > 600;
    }, { timeout: 30000 });
    await page.waitForTimeout(450); // settle async solves/effects
  };

  // ── first load: confirm the onboarding wizard greets a fresh user ──
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await waitMounted();
  const onbText = await page.evaluate(() => document.body.innerText);
  const onbShown = onbText.includes('right-size the workspace');
  // dismiss + mark onboarded so the per-tab loop isn't blocked by the overlay
  await page.evaluate(() => { try { localStorage.setItem('es_onboarded','1'); } catch(e){} });

  // ── per-stage loop ──
  for (const id of STAGES) {
    curErrors = [];
    await page.evaluate((s) => { localStorage.setItem('es_stage', s); localStorage.setItem('es_onboarded','1'); }, id);
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    try { await waitMounted(); } catch (e) { results.push({ id, ok:false, why:'did not mount: '+e.message.slice(0,120) }); continue; }
    const body = await page.evaluate(() => document.body.innerText);
    const errored = body.includes('This stage hit an error');
    const ok = !errored && curErrors.length === 0;
    results.push({ id, ok, why: errored ? 'ErrorBoundary card shown' : (curErrors[0]||'') , chars: body.length });
  }

  // ── Lab deep-test on Console ──
  let lab = { ok:false, why:'' };
  try {
    curErrors = [];
    await page.evaluate(() => { localStorage.setItem('es_stage','console'); localStorage.setItem('es_onboarded','1'); });
    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    await waitMounted();
    let body = await page.evaluate(() => document.body.innerText);
    const B = body.toLowerCase();
    const hasBand = B.includes('anatomy lab');
    const hasType = /\bLP\b|\bMILP\b/i.test(body) && B.includes('the model');
    // view real source
    const srcBtn = await page.getByText('view real source', { exact: false }).first();
    let srcOk = false;
    if (await srcBtn.count()) { await srcBtn.click(); await page.waitForTimeout(800);
      body = await page.evaluate(() => document.body.innerText); srcOk = body.includes('source excerpt') || body.includes('Profit Maximizer'); }
    // run live (procurement is the default sel → has a builder)
    const runBtn = await page.getByRole('button', { name: /Run live/i }).first();
    let runOk = false;
    if (await runBtn.count()) { await runBtn.click(); await page.waitForTimeout(3500);
      body = await page.evaluate(() => document.body.innerText);
      runOk = body.includes('Optimal') || body.includes('min cost') || body.includes('live'); }
    lab = { ok: hasBand && hasType && srcOk && runOk && curErrors.length===0,
            hasBand, hasType, srcOk, runOk, err: curErrors[0]||'' };
  } catch (e) { lab = { ok:false, why: e.message.slice(0,160) }; }

  await browser.close();

  // ── report ──
  console.log('\n=== ONBOARDING ===');
  console.log(onbShown ? 'PASS · wizard greeted a fresh user' : 'FAIL · wizard did not appear');
  console.log('\n=== TAB RENDER SMOKE (13) ===');
  let pass = 0;
  for (const r of results) { const tag = r.ok ? 'PASS' : 'FAIL';
    if (r.ok) pass++; console.log(`${tag}  ${r.id.padEnd(11)} ${r.ok ? '('+r.chars+' chars)' : '→ '+r.why}`); }
  console.log(`\n${pass}/${STAGES.length} tabs rendered clean`);
  console.log('\n=== SOLVER ANATOMY LAB ===');
  console.log(JSON.stringify(lab));
  const allOk = onbShown && pass === STAGES.length && lab.ok;
  console.log('\n' + (allOk ? '✅ SMOKE PASSED' : '❌ SMOKE HAD FAILURES'));
  process.exit(allOk ? 0 : 1);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
