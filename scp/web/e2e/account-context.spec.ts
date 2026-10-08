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

async function imported(page:Page,company='Account company A') {
  const chooser=page.waitForEvent('filechooser');
  if(await page.getByRole('button',{name:'Import a file',exact:true}).count()) {
    await page.getByRole('button',{name:'Import a file',exact:true}).click();
  } else {
    await page.getByRole('button',{name:'More',exact:true}).click();
    await page.getByRole('menuitem',{name:'Import a dataset file…'}).click();
  }
  await (await chooser).setFiles({name:'account.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture(company)))});
  await expect(page.locator('.topbar .company')).toHaveText(company);
}

async function signUp(page:Page) {
  await page.goto('/'); await imported(page); await page.goto('/#/account');
  await page.getByRole('tab',{name:'Make an account'}).click();
  const email=`accounts-${Date.now()}-${test.info().workerIndex}@example.invalid`;
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Your name').fill('Account audit owner');
  await page.getByLabel(/^Password/).fill('account-audit-20261001');
  await page.getByRole('button',{name:'Make the account',exact:true}).click();
  await expect(page.getByRole('button',{name:'Keep it on the server',exact:true})).toBeVisible();
  return email;
}

async function keep(page:Page) {
  await page.goto('/#/account');
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
}

async function stock(page:Page,qty:number) {
  await page.goto('/#/data/location_products/P%7CA');
  await page.locator('#on_hand').fill(String(qty)); await page.locator('#on_hand').press('Enter');
  await expect(page.locator('#on_hand')).toHaveValue(String(qty));
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
    const response=page.waitForResponse(url); release(); await (await response).finished();
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  }};
}

for(const endpoint of ['creation','document'] as const) {
  test(`keeping a browser company preserves edits made during the ${endpoint} response`,async({page})=>{
    await signUp(page);
    const delayed=await hold(page,endpoint==='creation'?'**/api/companies':'**/api/companies/*',endpoint==='creation'?'POST':'GET');
    await page.getByRole('button',{name:'Keep it on the server',exact:true}).click(); await delayed.arrived;
    await stock(page,35); await delayed.release();
    await expect(page.locator('#on_hand')).toHaveValue('35');
    await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('35');
    await page.goto('/#/account');
    await expect(page.getByRole('button',{name:'Keep it on the server',exact:true})).toBeVisible();
    // The original snapshot was saved, but the newer browser copy must not be silently replaced.
    page.once('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'Open Account company A',exact:true}).click();
    await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
    await page.goto('/#/data/location_products/P%7CA'); await expect(page.locator('#on_hand')).toHaveValue('10');
  });
}

test('a company created before an import cannot replace the newly imported company',async({page})=>{
  await signUp(page); const delayed=await hold(page,'**/api/companies');
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click(); await delayed.arrived;
  await imported(page,'Account company B'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Account company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Account company B');
});

test('a delayed server-company open cannot replace a newer import',async({page})=>{
  await signUp(page); await keep(page); await imported(page,'Account company B'); await page.goto('/#/account');
  const delayed=await hold(page,'**/api/companies/*','GET');
  await page.getByRole('button',{name:'Open Account company A',exact:true}).click(); await delayed.arrived;
  await imported(page,'Account company C'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Account company C');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Account company C');
});

test('a server-company response received after sign-out cannot reopen the company',async({page})=>{
  await signUp(page); await keep(page); await page.goto('/#/account');
  const delayed=await hold(page,'**/api/companies/*','GET');
  await page.getByRole('button',{name:'Open Account company A',exact:true}).click(); await delayed.arrived;
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.locator('.topbar .company')).toHaveCount(0);
  await delayed.release(); await expect(page.locator('.topbar .company')).toHaveCount(0);
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveCount(0);
});

test('the latest company selection wins when two open responses arrive in reverse order',async({page})=>{
  await signUp(page); await keep(page); await imported(page,'Account company B'); await keep(page);
  await page.goto('/#/account');
  const companies=await page.evaluate(async()=>{
    return await (await fetch('/api/companies',{headers:{}})).json();
  });
  const a=companies.find((c:{name:string})=>c.name==='Account company A');
  expect(a).toBeTruthy(); const delayed=await hold(page,`**/api/companies/${a.id}`,'GET');
  await page.getByRole('button',{name:'Open Account company A',exact:true}).click(); await delayed.arrived;
  await page.getByRole('button',{name:'Open Account company B',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Your company on the server',exact:true})).toHaveCount(0);
  await delayed.release(); await expect(page.locator('.topbar .company')).toHaveText('Account company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Account company B');
});

test('edits made during a server-company open remain in the browser after reload',async({page})=>{
  await signUp(page); await keep(page); await imported(page,'Account company B'); await page.goto('/#/account');
  const delayed=await hold(page,'**/api/companies/*','GET');
  await page.getByRole('button',{name:'Open Account company A',exact:true}).click(); await delayed.arrived;
  await stock(page,35); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Account company B');
  await expect(page.locator('#on_hand')).toHaveValue('35');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('35');
});

test('a pending upload cannot attach a server company after the owner signs out',async({page})=>{
  await signUp(page); const delayed=await hold(page,'**/api/companies');
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click(); await delayed.arrived;
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.getByLabel('Sign in',{exact:true})).toBeVisible();
  await delayed.release(); await page.reload(); await page.goto('/#/account');
  await expect(page.getByLabel('Sign in',{exact:true})).toBeVisible();
  await expect(page.locator('.topbar .company')).toHaveText('Account company A');
  // Its browser copy remains local; no authenticated company document should be fetched after sign-out.
  await expect(page.getByText("After signing in you can keep",{exact:false})).toBeVisible();
});

test('a saved company opens normally after signing back in with no dataset open',async({page})=>{
  const email=await signUp(page); await keep(page); await page.goto('/#/account');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.locator('.topbar .company')).toHaveCount(0);
  await page.getByLabel('E-mail').fill(email); await page.getByLabel('Password',{exact:true}).fill('account-audit-20261001');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('button',{name:'Open Account company A',exact:true}).click();
  await expect(page.locator('.topbar .company')).toHaveText('Account company A');
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Account company A');
});

test('an earlier open completion waits for the newer selection instead of opening an intermediate company',async({page})=>{
  await signUp(page); await keep(page); await imported(page,'Account company B'); await keep(page);
  await imported(page,'Account company C'); await page.goto('/#/account');
  const companies=await page.evaluate(async()=>{
    return await (await fetch('/api/companies',{headers:{}})).json();
  });
  const a=companies.find((c:{name:string})=>c.name==='Account company A');
  const b=companies.find((c:{name:string})=>c.name==='Account company B');
  const first=await hold(page,`**/api/companies/${a.id}`,'GET');
  const second=await hold(page,`**/api/companies/${b.id}`,'GET');
  await page.getByRole('button',{name:'Open Account company A',exact:true}).click(); await first.arrived;
  await page.getByRole('button',{name:'Open Account company B',exact:true}).click(); await second.arrived;
  await first.release(); await expect(page.locator('.topbar .company')).toHaveText('Account company C');
  await second.release(); await expect(page.locator('.topbar .company')).toHaveText('Account company B');
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
});

