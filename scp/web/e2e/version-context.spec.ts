import {expect,test,type Page} from '@playwright/test';

const fixture=(company:string)=>({
  settings:{company_name:company,planning_start:'2026-01-05',horizon_days:28,default_calendar:'CAL',wacc:0,holding_spread:0},
  calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
  locations:[{id:'P',type:'plant'},{id:'S',type:'supplier'}],
  products:[{id:'A',type:'FG',price:25}],
  location_products:[{location:'P',product:'A',on_hand:10,lot_sizing:{policy:'L4L'}}],
  purchasing_sources:[{id:'BUY-A',supplier:'S',location:'P',product:'A',price:10,lead_time_days:1}],
  demand:[{id:'F1',location:'P',product:'A',date:'2026-01-12',qty:100,kind:'forecast'}],
});

async function imported(page:Page,company='Version company A') {
  const chooser=page.waitForEvent('filechooser');
  if(await page.getByRole('button',{name:'Import a file',exact:true}).count()) {
    await page.getByRole('button',{name:'Import a file',exact:true}).click();
  } else {
    await page.getByRole('button',{name:'More',exact:true}).click();
    await page.getByRole('menuitem',{name:'Import a dataset file…'}).click();
  }
  await (await chooser).setFiles({name:'version.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture(company)))});
  await expect(page.locator('.topbar .company')).toHaveText(company);
}

async function open(page:Page) {
  await page.goto('/'); await imported(page);
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({timeout:45000});
  await page.goto('/#/versions');
}

async function saveBase(page:Page) {
  await page.getByLabel('Version name').fill('Baseline');
  await page.getByRole('button',{name:'Save as base version',exact:true}).click();
  await expect(page.locator('.version-chip')).toContainText('Baseline · base');
  return (await page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Working copy',exact:true})}).locator('b').first().textContent())!;
}

async function stock(page:Page,qty:number) {
  await page.goto('/#/data/location_products/P%7CA');
  await page.locator('#on_hand').fill(String(qty)); await page.locator('#on_hand').press('Enter');
  await expect(page.locator('#on_hand')).toHaveValue(String(qty));
}

async function scenario(page:Page,base:string) {
  await stock(page,40); await page.goto('/#/versions');
  await page.getByLabel('Version name').fill('More stock');
  await page.getByRole('button',{name:`Save as new scenario of ${base}`,exact:true}).click();
  await expect(page.locator('.version-chip')).toContainText('More stock · scenario');
  return (await page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Working copy',exact:true})}).locator('b').first().textContent())!;
}

async function hold(page:Page,url:string,method='POST') {
  let release!:()=>void,notify!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  const arrived=new Promise<void>(resolve=>{notify=resolve;});
  await page.route(url,async route=>{
    if(route.request().method()!==method) return route.continue();
    const response=await route.fetch(); notify(); await gate; await route.fulfill({response});
  });
  return {arrived,release:async()=>{
    const response=page.waitForResponse(url);
    release(); await (await response).finished();
  }};
}

test('version journey independently reconciles a stock scenario and retains the immutable baseline after promotion',async({page})=>{
  await open(page); const base=await saveBase(page);
  const baselineRow=page.locator('tbody tr').filter({has:page.getByRole('button',{name:`Open ${base}`,exact:true})});
  const baselineSha=await baselineRow.locator('td[title]').getAttribute('title');
  const variant=await scenario(page,base);
  await page.getByRole('button',{name:`Compare ${base} as A`,exact:true}).click();
  await page.getByRole('button',{name:`Compare ${variant} as B`,exact:true}).click();
  await page.getByRole('button',{name:'Compare',exact:true}).click();
  // Demand 100 at INR10/unit: opening stock 10 -> buy90/cost900; stock40 -> buy60/cost600.
  await expect(page.getByRole('row',{name:/^Total plan cost/})).toHaveText('Total plan cost₹900₹600−₹300');
  await page.locator('tr.clickable',{hasText:'location products'}).click();
  await expect(page.getByText('on_hand: 10 → 40')).toBeVisible();
  await page.getByRole('button',{name:`Promote ${variant}`,exact:true}).click();
  await expect(baselineRow).toContainText('superseded');
  expect(await baselineRow.locator('td[title]').getAttribute('title')).toBe(baselineSha);
  await page.reload(); await page.goto('/#/data/location_products/P%7CA');
  await expect(page.locator('#on_hand')).toHaveValue('40');
  await page.screenshot({path:test.info().outputPath('promoted-stock-scenario.png'),fullPage:true});
});

test('an edit during a version save remains unsaved against the saved snapshot after reload',async({page})=>{
  await open(page); const delayed=await hold(page,'**/api/versions');
  await page.getByLabel('Version name').fill('Snapshot stock 10');
  await page.getByRole('button',{name:'Save as base version',exact:true}).click(); await delayed.arrived;
  await stock(page,25); await delayed.release();
  await expect(page.locator('.version-chip')).toContainText('unsaved changes');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('25');
  await expect(page.locator('.version-chip')).toContainText('unsaved changes');
  await page.goto('/#/versions');
  const id=(await page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Working copy',exact:true})}).locator('b').first().textContent())!;
  await page.getByRole('button',{name:`Compare ${id} as A`,exact:true}).click();
  await page.getByRole('button',{name:'Compare __working__ as B',exact:true}).click();
  await page.getByRole('button',{name:'Compare',exact:true}).click();
  await page.locator('tr.clickable',{hasText:'location products'}).click();
  await expect(page.getByText('on_hand: 10 → 25')).toBeVisible();
  await expect(page.getByRole('row',{name:/^Total plan cost/})).toHaveText('Total plan cost₹900₹750−₹150');
  await page.screenshot({path:test.info().outputPath('saved-snapshot-with-new-unsaved-stock.png'),fullPage:true});
});

test('a late base save cannot attach an old version to an imported company',async({page})=>{
  await open(page); const delayed=await hold(page,'**/api/versions');
  await page.getByLabel('Version name').fill('Old company snapshot');
  await page.getByRole('button',{name:'Save as base version',exact:true}).click(); await delayed.arrived;
  await imported(page,'Version company B'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Version company B');
  await expect(page.locator('.version-chip')).toHaveCount(0);
  await page.reload(); await expect(page.locator('.version-chip')).toHaveCount(0);
});

test('a delayed branch cannot replace the company opened while the branch was running',async({page})=>{
  await open(page); const base=await saveBase(page);
  const delayed=await hold(page,`**/api/versions/${base}/branch`);
  await page.getByRole('button',{name:`Branch ${base}`,exact:true}).click(); await delayed.arrived;
  await imported(page,'Version company B'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Version company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Version company B');
});

for(const action of ['Branch','Promote']) {
  test(`${action} requires acknowledgement before replacing unsaved scenario edits`,async({page})=>{
    await open(page); const base=await saveBase(page); const variant=await scenario(page,base);
    await stock(page,45); await page.goto('/#/versions');
    page.on('dialog',dialog=>dialog.dismiss());
    await page.getByRole('button',{name:`${action} ${variant}`,exact:true}).click();
    await expect(page.getByRole('button',{name:`Open ${variant}`,exact:true})).toBeEnabled();
    await page.goto('/#/data/location_products/P%7CA');
    await expect(page.locator('#on_hand')).toHaveValue('45');
    await expect(page.locator('.version-chip')).toContainText('unsaved changes');
  });

  test(`${action} can open the saved scenario after explicitly acknowledging replacement`,async({page})=>{
    await open(page); const base=await saveBase(page); const variant=await scenario(page,base);
    await stock(page,45); await page.goto('/#/versions');
    let message='';
    page.on('dialog',async dialog=>{message=dialog.message(); await dialog.accept();});
    await page.getByRole('button',{name:`${action} ${variant}`,exact:true}).click();
    await expect(page.getByRole('button',{name:`Open ${variant}`,exact:true})).toBeEnabled();
    expect(message).toContain('unsaved');
    await page.goto('/#/data/location_products/P%7CA');
    await expect(page.locator('#on_hand')).toHaveValue('40');
    await expect(page.locator('.version-chip')).not.toContainText('unsaved changes');
  });
}

test('discarding a scenario changes its status without marking unsaved edits as saved',async({page})=>{
  await open(page); const base=await saveBase(page); const variant=await scenario(page,base);
  await stock(page,45); await page.goto('/#/versions');
  page.on('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:`Discard ${variant}`,exact:true}).click();
  await expect(page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Working copy',exact:true})})).toContainText('discarded');
  await expect(page.locator('.version-chip')).toContainText('unsaved changes');
  await page.reload(); await page.goto('/#/data/location_products/P%7CA');
  await expect(page.locator('#on_hand')).toHaveValue('45');
  await expect(page.locator('.version-chip')).toContainText('unsaved changes');
});

test('an edit during a version open survives the delayed version response',async({page})=>{
  await open(page); const base=await saveBase(page);
  const delayed=await hold(page,`**/api/versions/${base}`,'GET');
  await page.getByRole('button',{name:`Open ${base}`,exact:true}).click(); await delayed.arrived;
  await stock(page,35); await delayed.release();
  await page.goto('/#/versions');
  await expect(page.getByRole('button',{name:'Save as base version',exact:true})).toBeEnabled();
  await page.goto('/#/data/location_products/P%7CA');
  await expect(page.locator('#on_hand')).toHaveValue('35');
  await expect(page.locator('.version-chip')).toContainText('unsaved changes');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('35');
});

test('a working-copy comparison reports edits made during its calculation instead of displaying stale results',async({page})=>{
  await open(page); const base=await saveBase(page); await stock(page,40); await page.goto('/#/versions');
  const delayed=await hold(page,'**/api/compare');
  await page.getByRole('button',{name:`Compare ${base} as A`,exact:true}).click();
  await page.getByRole('button',{name:'Compare __working__ as B',exact:true}).click();
  await page.getByRole('button',{name:'Compare',exact:true}).click(); await delayed.arrived;
  await page.getByRole('button',{name:'Undo',exact:true}).click(); await delayed.release();
  await expect(page.locator('.banner.error')).toContainText('The working copy was edited');
  await expect(page.getByText('Plan side by side (MRP)',{exact:true})).toHaveCount(0);
  await page.goto('/#/data/location_products/P%7CA'); await expect(page.locator('#on_hand')).toHaveValue('10');
});

test('a delayed branch document cannot replace or detach a different live server company',async({page})=>{
  await open(page); await page.goto('/#/account');
  await page.getByRole('tab',{name:'Make an account'}).click();
  await page.getByLabel('E-mail').fill(`versions-${Date.now()}@example.invalid`);
  await page.getByLabel('Your name').fill('Version audit owner');
  await page.getByLabel(/^Password/).fill('version-audit-20261001');
  await page.getByRole('button',{name:'Make the account',exact:true}).click();
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.goto('/#/versions'); const base=await saveBase(page);
  // Hold the second request, after the branch has already been created in company A's scope.
  const delayed=await hold(page,'**/api/versions/*','GET');
  await page.getByRole('button',{name:`Branch ${base}`,exact:true}).click(); await delayed.arrived;
  await imported(page,'Version company B'); await page.goto('/#/account');
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Version company B');
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.reload();
  await expect(page.locator('.topbar .company')).toHaveText('Version company B');
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.screenshot({path:test.info().outputPath('live-company-b-after-delayed-branch.png'),fullPage:true});
});
