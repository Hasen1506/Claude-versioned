import { expect, test, type Page } from '@playwright/test';
import { readFile, writeFile } from 'node:fs/promises';

test.use({timezoneId:'Asia/Kolkata'});

function fixture(fixed = false) {
  return {
    settings: {company_name:'Manufacturing journey',planning_start:'2026-01-05',horizon_days:28,default_calendar:'CAL',capacity_constrained:true,wacc:0,holding_spread:0},
    calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
    locations:[{id:'P',type:'plant'},{id:'S',type:'supplier'}],
    products:[{id:'A',type:'FG',price:100},{id:'B',type:'RM'},{id:'C',type:'RM'}],
    location_products:['A','B','C'].map(product=>({location:'P',product,on_hand:fixed && product!=='A'?100:0,lot_sizing:{policy:'L4L'}})),
    resources:[{id:'M1',location:'P',hours_per_shift:4,efficiency:1,cost_per_hour:100}],
    production_sources:[{id:'PV-A',location:'P',product:'A',components:[{product:'B',qty:2},{product:'C',qty:fixed?5:1,fixed_qty:fixed}],operations:[{seq:10,resource:'M1',setup_hours:2,run_hours_per_unit:0.5}]}],
    purchasing_sources:[{id:'PIR-B',supplier:'S',location:'P',product:'B',price:10,lead_time_days:3},{id:'PIR-C',supplier:'S',location:'P',product:'C',price:5,lead_time_days:1}],
    demand:[{location:'P',product:'A',date:'2026-01-12',qty:20,kind:'forecast'}],
  };
}

async function open(page:Page,fixed=false,data:unknown=fixture(fixed)) {
  await page.goto('/');
  const chooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'Import a file',exact:true}).click();
  await (await chooser).setFiles({name:'manufacturing.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({timeout:45000});
}

async function exported(page:Page) {
  await page.getByRole('button',{name:'More',exact:true}).click();
  const download=page.waitForEvent('download');
  await page.getByRole('menuitem',{name:'Export this dataset'}).click();
  const file=await (await download).path();
  return JSON.parse(await readFile(file!,'utf-8'));
}

async function firm(page:Page,count:number) {
  await page.goto('/#/execution/orders');
  const calculate=page.getByRole('button',{name:/^(Recalculate the supply plan|Calculate the supply plan)$/});
  // pages load on demand: wait for the firm zone to be drawn before asking whether the plan needs calculating
  await expect(page.getByRole('heading',{name:/^Firm zone:/})).toBeVisible({timeout:45000});
  if(await calculate.count()) await calculate.click();
  await page.getByRole('button',{name:`Make ${count} order${count===1?'':'s'} firm`,exact:true}).click();
  await expect(page.getByText(new RegExp(`${count} planned order${count===1?'':'s'} firmed`))).toBeVisible();
}

test('manufacturing: forecast → finite plan → promise → purchases → partial production → roll → shipment reconciles',async ({page})=>{
  await open(page);
  await page.goto('/#/finance');
  await expect(page.locator('.tile',{has:page.getByText('Plan cost',{exact:true})}).locator('.value')).toHaveText('₹1.7K');
  await expect(page.locator('.tile',{has:page.getByText('Revenue served',{exact:true})}).locator('.value')).toHaveText('₹2K');
  await expect(page.locator('.tile',{has:page.getByText('Margin',{exact:true})}).locator('.value')).toHaveText('₹300');
  await page.goto('/#/promise/simulate');
  await expect(page.getByLabel('Wanted on')).toHaveValue('2026-01-12');
  await page.getByLabel('Quantity',{exact:true}).fill('20');
  await page.getByLabel("Customer's order number").fill('MANUFACTURE-20');
  await page.getByRole('button',{name:'Check availability'}).click();
  await page.getByRole('button',{name:'Take this order'}).click();
  await expect(page.locator('.banner.info',{hasText:'Saved'})).toContainText('SO-00001 taken: 20');
  // promised on new production: taking the order makes that production firm at once; the purchases are left to firm
  await expect(page.locator('.banner.info',{hasText:'Saved'})).toContainText('Made firm for it: PRD-');
  await firm(page,2);
  let data=await exported(page);
  await writeFile(test.info().outputPath('firmed.json'),JSON.stringify(data,null,2));
  expect(data.receipts.map((r:any)=>[r.kind,r.product,r.qty])).toEqual(expect.arrayContaining([['production','A',20],['purchase','B',40],['purchase','C',20]]));
  const prd=data.receipts.find((r:any)=>r.kind==='production');
  expect(prd.start_date).toBe('2026-01-09'); expect(prd.due_date).toBe('2026-01-12');
  await page.locator('#post-date').fill('2026-01-09');
  for(const r of data.receipts.filter((r:any)=>r.kind==='purchase')) {
    await page.getByRole('button',{name:`Receive ${r.id}`,exact:true}).click();
    await expect(page.locator('.banner.info',{hasText:'Posted'})).toContainText(r.id);
  }
  await page.locator('#post-date').fill('2026-01-11');
  await page.getByRole('button',{name:`Post part of ${prd.id}`}).click();
  await page.getByLabel(`Quantity for ${prd.id}`).fill('8');
  await page.getByRole('button',{name:'Confirm 8',exact:true}).click();
  await expect(page.locator('.banner.info',{hasText:'Posted'})).toContainText('8 made');
  await page.goto('/#/execution/roll');
  await page.getByRole('button',{name:'Move the plan to this date'}).click();
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toBeVisible();
  data=await exported(page);
  expect(Object.fromEntries(data.location_products.map((r:any)=>[r.product,r.on_hand]))).toEqual({A:8,B:24,C:12});
  expect(data.receipts.find((r:any)=>r.id===prd.id).qty).toBe(12);
  await page.goto('/#/execution/orders');
  await page.getByRole('button',{name:`Receive ${prd.id}`,exact:true}).click();
  await expect(page.locator('.banner.info',{hasText:'Posted'})).toContainText('12 made');
  await page.getByRole('button',{name:'Deliver SO-00001',exact:true}).click();
  await expect(page.locator('.banner.info',{hasText:'Posted'})).toContainText('20 delivered');
  await page.goto('/#/execution/roll');
  await page.getByLabel('Roll forward to').fill('2026-01-13');
  await page.getByRole('button',{name:'Move the plan to this date'}).click();
  await expect(page.getByText('Rolled from Mon 12 Jan to Tue 13 Jan')).toBeVisible();
  data=await exported(page);
  expect(Object.fromEntries(data.location_products.map((r:any)=>[r.product,r.on_hand]))).toEqual({A:0,B:0,C:0});
  expect(data.receipts).toHaveLength(0);
  expect(data.demand.filter((r:any)=>r.kind==='sales_order')).toHaveLength(0);
  expect(data.closed_orders).toHaveLength(4);
  expect(data.closed_orders.find((r:any)=>r.kind==='sales').delivered_qty).toBe(20);
  await page.screenshot({path:test.info().outputPath('manufacturing-reconciled.png'),fullPage:true});
});

test('production form previews the fixed component once for a partial receipt',async ({page})=>{
  await open(page,true); await firm(page,1);
  await page.getByRole('button',{name:'Post part of PRD-00001'}).click();
  await page.getByLabel('Quantity for PRD-00001').fill('8');
  const parts=page.locator('tr.sub .small.muted').filter({hasText:'Parts issued with it'});
  await expect(parts).toContainText(/B\s+16/);
  await expect(parts).toContainText(/C\s+5/);
  await page.getByLabel('Enter the parts actually used').check();
  await expect(page.getByLabel('Used C')).toHaveValue('5.000000');
  await page.getByRole('button',{name:'Confirm 8',exact:true}).click();
  await expect(page.locator('.banner.info',{hasText:'Posted'})).toContainText('8 made');
  const data=await exported(page);
  expect(data.movements.filter((r:any)=>r.type==='issue').map((r:any)=>[r.product,r.qty])).toEqual([['B',16],['C',5]]);
  await page.goto('/#/execution/journal');
  await page.getByRole('button',{name:'Reverse GM-00001',exact:true}).click();
  await expect(page.locator('.banner.info',{hasText:'Reversed'})).toContainText('reversed');
  await page.goto('/#/execution/orders');
  await page.getByRole('button',{name:'Post part of PRD-00001'}).click();
  await page.getByLabel('Quantity for PRD-00001').fill('8');
  await page.getByLabel('Enter the parts actually used').check();
  await expect(page.getByLabel('Used B')).toHaveValue('16.000000');
  await expect(page.getByLabel('Used C')).toHaveValue('5.000000');
  await page.screenshot({path:test.info().outputPath('production-parts-after-reversal.png'),fullPage:true});
});

test('a small fractional production receipt retains its open quantity and component precision',async({page})=>{
  const raw={...fixture(),demand:[],receipts:[{id:'WO-SMALL',kind:'production',location:'P',product:'A',qty:0.0004,due_date:'2026-01-12',source:'PV-A'}],products:[{id:'A',type:'FG',whole_units:false},{id:'B',type:'RM'},{id:'C',type:'RM'}]};
  await open(page,false,raw);
  await page.goto('/#/execution/orders');
  await page.getByRole('button',{name:'Post part of WO-SMALL'}).click();
  await expect(page.getByLabel('Quantity for WO-SMALL')).toHaveValue('0.0004');
  await page.getByLabel('Enter the parts actually used').check();
  await expect(page.getByLabel('Used B')).toHaveValue('0.000800');
  await expect(page.getByLabel('Used C')).toHaveValue('0.000400');
});

test('component preview recovers from failure and ignores an older quantity response',async({page})=>{
  await open(page,true); await firm(page,1);
  let fail=true;
  let release!:()=>void;
  const held=new Promise<void>(resolve=>{release=resolve;});
  let announce!:()=>void;
  const requested=new Promise<void>(resolve=>{announce=resolve;});
  await page.route('**/api/actuals/production-usage',async route=>{
    if(fail) {
      fail=false;
      await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Preview temporarily unavailable'})});
    } else if(route.request().postDataJSON().qty===8) {
      const response=await route.fetch();
      announce(); await held; await route.fulfill({response});
    } else await route.continue();
  });
  await page.getByRole('button',{name:'Post part of PRD-00001'}).click();
  await page.getByRole('button',{name:'Read parts again'}).click();
  const parts=page.locator('tr.sub .small.muted').filter({hasText:'Parts issued with it'});
  await expect(parts).toContainText(/B\s+40/);
  await page.getByLabel('Quantity for PRD-00001').fill('8');
  await requested;
  await expect(page.getByRole('button',{name:'Confirm 8',exact:true})).toBeDisabled();
  await page.getByLabel('Quantity for PRD-00001').fill('12');
  await expect(parts).toContainText(/B\s+24/);
  const oldResponse=page.waitForResponse(r=>r.url().endsWith('/api/actuals/production-usage')&&r.request().postDataJSON().qty===8);
  release(); await oldResponse;
  await page.getByLabel('Enter the parts actually used').check();
  await expect(page.getByLabel('Used B')).toHaveValue('24.000000');
  await expect(page.getByRole('button',{name:'Confirm 12',exact:true})).toBeEnabled();
});
