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

async function imported(page:Page,company='Live company A') {
  const chooser=page.waitForEvent('filechooser');
  if(await page.getByRole('button',{name:'Import a file',exact:true}).count()) await page.getByRole('button',{name:'Import a file',exact:true}).click();
  else {
    await page.getByRole('button',{name:'More',exact:true}).click();
    await page.getByRole('menuitem',{name:'Import a dataset file…'}).click();
  }
  await (await chooser).setFiles({name:'live.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture(company)))});
  await expect(page.locator('.topbar .company')).toHaveText(company);
}

async function live(page:Page) {
  await page.goto('/'); await imported(page); await page.goto('/#/account');
  await page.getByRole('tab',{name:'Make an account'}).click();
  await page.getByLabel('E-mail').fill(`live-${Date.now()}-${test.info().workerIndex}@example.invalid`);
  await page.getByLabel('Your name').fill('Live audit owner');
  await page.getByLabel(/^Password/).fill('live-audit-20261001');
  await page.getByRole('button',{name:'Make the account',exact:true}).click();
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  return page.evaluate(()=>({
    company:JSON.parse(localStorage.getItem('scp.company.v1')!),
    session:JSON.parse(localStorage.getItem('scp.session.v1')!),
  }));
}

async function stock(page:Page,qty:number) {
  await page.goto('/#/data/location_products/P%7CA');
  await page.locator('#on_hand').fill(String(qty)); await page.locator('#on_hand').press('Enter');
  await expect(page.locator('#on_hand')).toHaveValue(String(qty));
}

async function version(page:Page) {
  await page.goto('/#/versions'); await page.getByLabel('Version name').fill('Stock snapshot');
  await page.getByRole('button',{name:'Save as base version',exact:true}).click();
  const panel=page.locator('section.panel').filter({has:page.getByRole('heading',{name:'Working copy',exact:true})});
  await expect(panel).toContainText('Stock snapshot'); const id=(await panel.locator('b').first().textContent())!;
  await page.getByRole('button',{name:`Open ${id}`,exact:true}).click();
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  return id;
}

async function hold(page:Page,url:string,method='GET') {
  let release!:()=>void,notify!:()=>void,used=false;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  const arrived=new Promise<void>(resolve=>{notify=resolve;});
  await page.route(url,async route=>{
    if(used||route.request().method()!==method) return route.continue();
    used=true; const response=await route.fetch(); notify(); await gate; await route.fulfill({response});
  });
  return {arrived,release:async()=>{
    const response=page.waitForResponse(url); release(); await (await response).finished();
    await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
  }};
}

for(const accept of [false,true]) test(`returning to live data ${accept?'acknowledges':'can cancel'} replacement of unsaved version edits`,async({page})=>{
  await live(page); await version(page); await stock(page,35);
  let confirmed=false;
  page.once('dialog',async d=>{confirmed=true; expect(d.message()).toContain('unsaved'); await (accept?d.accept():d.dismiss());});
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click();
  expect(confirmed).toBe(true);
  await expect(page.locator('#on_hand')).toHaveValue(accept?'10':'35');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue(accept?'10':'35');
});

test('a delayed live-data return cannot overwrite a newer imported company',async({page})=>{
  const {company}=await live(page); await version(page);
  const delayed=await hold(page,`**/api/companies/${company.id}`);
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click(); await delayed.arrived;
  await imported(page,'Live company B'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Live company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Live company B');
});

test('an edit made during live-data return survives the response and reload',async({page})=>{
  const {company}=await live(page); await version(page);
  const delayed=await hold(page,`**/api/companies/${company.id}`);
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click(); await delayed.arrived;
  await stock(page,35); await delayed.release();
  await expect(page.locator('#on_hand')).toHaveValue('35');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('35');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
});

test('publishing a version cannot use another company opened during its revision lookup',async({page})=>{
  await live(page); await version(page); const delayed=await hold(page,'**/api/companies');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Make this the live data',exact:true}).click(); await delayed.arrived;
  await imported(page,'Live company B'); await page.goto('/#/account');
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await version(page); await stock(page,55);
  await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Live company B');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  await expect(page.locator('#on_hand')).toHaveValue('55');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('55');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  const serverStock=await page.evaluate(async()=>{
    const company=JSON.parse(localStorage.getItem('scp.company.v1')!);
    const session=JSON.parse(localStorage.getItem('scp.session.v1')!);
    const doc=await (await fetch(`/api/companies/${company.id}`,{headers:{Authorization:`Bearer ${session.token}`}})).json();
    return doc.dataset.location_products[0].on_hand;
  });
  expect(serverStock).toBe(10);
});

test('a delayed history restore document cannot replace a newer imported company',async({page})=>{
  const {company}=await live(page); await stock(page,25);
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.goto('/#/history');
  const created=page.locator('ol.history > li').filter({has:page.getByText('created',{exact:true})});
  const delayed=await hold(page,`**/api/companies/${company.id}`);
  page.once('dialog',d=>d.accept()); await created.getByRole('button',{name:'Put back to this',exact:true}).click(); await delayed.arrived;
  await imported(page,'Live company B'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Live company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Live company B');
});

test('a reload refresh cannot reopen live data over a version of the same company',async({page})=>{
  const {company,session}=await live(page); const id=await version(page);
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  // Save stock25 remotely while this browser still holds stock10; hold the reload's new document.
  await page.evaluate(async({company,session})=>{
    const headers={'Content-Type':'application/json',Authorization:`Bearer ${session.token}`};
    const doc=await (await fetch(`/api/companies/${company.id}`,{headers})).json();
    doc.dataset.location_products[0].on_hand=25;
    const response=await fetch(`/api/companies/${company.id}`,{method:'PUT',headers,body:JSON.stringify({dataset:doc.dataset,base_revision:doc.meta.revision})});
    if(!response.ok) throw new Error(await response.text());
  },{company,session});
  const delayed=await hold(page,`**/api/companies/${company.id}`);
  await page.reload(); await delayed.arrived;
  await page.goto('/#/versions'); await page.getByRole('button',{name:`Open ${id}`,exact:true}).click();
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  await delayed.release(); await page.goto('/#/data/location_products/P%7CA');
  await expect(page.locator('#on_hand')).toHaveValue('10');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
});

test('opening a company from server-only storage cannot undo a sign-out during recovery',async({page})=>{
  const {company}=await live(page);
  await page.evaluate(()=>localStorage.removeItem('scp.dataset.v1'));
  const delayed=await hold(page,`**/api/companies/${company.id}`);
  await page.reload(); await delayed.arrived; await page.goto('/#/account');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.getByLabel('Sign in',{exact:true})).toBeVisible();
  await delayed.release(); await expect(page.locator('.topbar .company')).toHaveCount(0);
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveCount(0);
});

for(const failure of [false,true]) test(`a delayed blank-company ${failure?'failure':'success'} cannot replace a newer import`,async({page})=>{
  await live(page);
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'More',exact:true}).click();
  await page.getByRole('menuitem',{name:'Close the company',exact:true}).click();
  await page.getByRole('button',{name:'Start with an empty company',exact:true}).click();
  await page.getByLabel('Company name',{exact:true}).fill('Pending blank company');
  const delayed=await hold(page,'**/api/companies','POST');
  // For failure, delay a known error instead of creating a server document.
  if(failure) {
    await page.unroute('**/api/companies');
    let done!:()=>void,seen!:()=>void;
    const gate=new Promise<void>(r=>done=r),arrived=new Promise<void>(r=>seen=r);
    await page.route('**/api/companies',async route=>{
      if(route.request().method()!=='POST') return route.continue();
      seen(); await gate; await route.fulfill({status:503,json:{detail:'Audit server temporarily unavailable'}});
    });
    await page.getByRole('button',{name:'Create the company',exact:true}).click(); await arrived;
    await imported(page,'Live company B');
    const response=page.waitForResponse('**/api/companies'); done(); await (await response).finished();
  } else {
    await page.getByRole('button',{name:'Create the company',exact:true}).click(); await delayed.arrived;
    await imported(page,'Live company B'); await delayed.release();
  }
  await expect(page.locator('.topbar .company')).toHaveText('Live company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Live company B');
});

test('live-data return reports a failed read and can retry without losing its version',async({page})=>{
  const {company}=await live(page); await version(page);
  await page.route(`**/api/companies/${company.id}`,route=>route.fulfill({status:503,json:{detail:'Audit live-data read failed'}}));
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Audit live-data read failed');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeEnabled();
  await page.unroute(`**/api/companies/${company.id}`);
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
});

test('publishing a version does not implicitly publish edits made during the revision lookup',async({page})=>{
  await live(page); await version(page); const delayed=await hold(page,'**/api/companies');
  page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'Make this the live data',exact:true}).click(); await delayed.arrived;
  await stock(page,35); await delayed.release();
  await expect(page.getByRole('alert')).toContainText('The working copy was edited');
  await expect(page.locator('#on_hand')).toHaveValue('35');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('35');
});

test('a new stock edit survives a delayed history restoration document and reload',async({page})=>{
  const {company}=await live(page); await stock(page,25);
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.goto('/#/history');
  const created=page.locator('ol.history > li').filter({has:page.getByText('created',{exact:true})});
  const delayed=await hold(page,`**/api/companies/${company.id}`);
  page.once('dialog',d=>d.accept()); await created.getByRole('button',{name:'Put back to this',exact:true}).click(); await delayed.arrived;
  await stock(page,35); await delayed.release();
  await expect(page.locator('#on_hand')).toHaveValue('35');
  await page.reload(); await expect(page.locator('#on_hand')).toHaveValue('35');
});

test('server-only storage recovery opens its company normally when its request is current',async({page})=>{
  await live(page); await page.evaluate(()=>localStorage.removeItem('scp.dataset.v1'));
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Live company A');
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await page.goto('/#/data/location_products/P%7CA'); await expect(page.locator('#on_hand')).toHaveValue('10');
});

test('blank-company creation falls back locally on a current server failure',async({page})=>{
  await live(page); page.once('dialog',d=>d.accept());
  await page.getByRole('button',{name:'More',exact:true}).click();
  await page.getByRole('menuitem',{name:'Close the company',exact:true}).click();
  await page.getByRole('button',{name:'Start with an empty company',exact:true}).click();
  await page.getByLabel('Company name',{exact:true}).fill('Local fallback company');
  await page.route('**/api/companies',route=>route.request().method()==='POST'
    ?route.fulfill({status:503,json:{detail:'Audit create failed'}}):route.continue());
  await page.getByRole('button',{name:'Create the company',exact:true}).click();
  await expect(page.locator('.topbar .company')).toHaveText('Local fallback company');
  await expect(page.locator('.save-chip .save-long')).toHaveText('In this browser only');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Local fallback company');
});

async function peerChange(page:Page,field:'stock'|'demand') {
  await page.evaluate(async field=>{
    const company=JSON.parse(localStorage.getItem('scp.company.v1')!);
    const owner=JSON.parse(localStorage.getItem('scp.session.v1')!);
    const ownerHeaders={'Content-Type':'application/json',Authorization:`Bearer ${owner.token}`};
    const email=`peer-${Date.now()}@example.invalid`;
    const json=async(url:string,init:RequestInit)=>{
      const response=await fetch(url,init);
      if(!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
      return await response.json();
    };
    const members=await json(`/api/companies/${company.id}/members`,{method:'POST',headers:ownerHeaders,body:JSON.stringify({email,role:'planner'})});
    const peer=await json('/api/auth/signup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,name:'Audit peer',password:`peer-${crypto.randomUUID()}`})});
    const headers={'Content-Type':'application/json',Authorization:`Bearer ${peer.token}`};
    // nobody joins unasked: the peer accepts the invitation's link
    const link=members.find((m:{email:string;invite_link?:string|null})=>m.email===email).invite_link as string;
    await json('/api/auth/invites/accept',{method:'POST',headers,body:JSON.stringify({token:link.split('/').pop()})});
    const doc=await json(`/api/companies/${company.id}`,{headers});
    if(field==='stock') doc.dataset.location_products[0].on_hand=25;
    else doc.dataset.demand[0].qty=110;
    await json(`/api/companies/${company.id}`,{method:'PUT',headers,body:JSON.stringify({dataset:doc.dataset,base_revision:doc.meta.revision})});
  },field);
}

test('an automatic merge finishing after opening a version cannot resave that version as live data',async({page})=>{
  const {company}=await live(page); const id=await version(page);
  await page.getByRole('button',{name:'Back to the live data',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);
  await peerChange(page,'demand');
  const delayed=await hold(page,`**/api/companies/${company.id}/merge`,'POST');
  await stock(page,35); await delayed.arrived;
  await page.goto('/#/versions');
  page.once('dialog',d=>d.accept()); await page.getByRole('button',{name:`Open ${id}`,exact:true}).click();
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  let extraMerges=0;
  const extraResponses:Promise<unknown>[]=[];
  page.on('request',r=>{
    if(r.method()==='POST'&&r.url().endsWith(`/api/companies/${company.id}/merge`)) {
      extraMerges++;
      extraResponses.push(r.response().then(response=>response?.finished()));
    }
  });
  await delayed.release(); await page.goto('/#/data/location_products/P%7CA');
  await Promise.all(extraResponses);
  await expect(page.locator('#on_hand')).toHaveValue('10');
  await expect(page.getByRole('button',{name:'Back to the live data',exact:true})).toBeVisible();
  const server=await page.evaluate(async()=>{
    const company=JSON.parse(localStorage.getItem('scp.company.v1')!);
    const session=JSON.parse(localStorage.getItem('scp.session.v1')!);
    return await (await fetch(`/api/companies/${company.id}`,{headers:{Authorization:`Bearer ${session.token}`}})).json();
  });
  await test.info().attach('live-server-after-merge',{body:JSON.stringify({extraMerges,stock:server.dataset.location_products[0].on_hand,demand:server.dataset.demand[0].qty}),contentType:'application/json'});
  expect(server.dataset.location_products[0].on_hand).toBe(35);
  expect(server.dataset.demand[0].qty).toBe(110);
  expect(extraMerges).toBe(0);
});

test('a manual merge finishing after import cannot replace the imported company',async({page})=>{
  const {company}=await live(page); await peerChange(page,'stock'); await stock(page,35);
  await expect(page.locator('.save-chip .save-long')).toHaveText('Not saved · saved by someone else');
  await page.getByRole('button',{name:'Merge both',exact:true}).click();
  await expect(page.locator('.clash-chooser')).toBeVisible();
  const delayed=await hold(page,`**/api/companies/${company.id}/merge`,'POST');
  await page.locator('.clash-chooser').getByRole('button',{name:/^Merge, keeping/}).click(); await delayed.arrived;
  await imported(page,'Live company B'); await delayed.release();
  await expect(page.locator('.topbar .company')).toHaveText('Live company B');
  await page.reload(); await expect(page.locator('.topbar .company')).toHaveText('Live company B');
});

