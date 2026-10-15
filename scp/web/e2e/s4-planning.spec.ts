import {expect,test,type Page} from '@playwright/test';

// ENTERPRISE_PLAN phase 2: planning defects measured against the S/4 guide, used through the screens.

async function imported(page:Page,name:string,data:object) {
  await page.goto('/');
  const chooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'Import a file',exact:true}).click();
  await (await chooser).setFiles({name:`${name}.json`,mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
  await expect(page.locator('.topbar .company')).toHaveText(name);
}

// 2.1 (§8.1): a casing PO due a week after the customer order. A new order (3 days) could still come on time, so
// without a rescheduling horizon the plan orders again beside the PO; with one, it brings the PO in instead.
const lateCasing={
  settings:{company_name:'Late Casing Pumps',planning_start:'2026-01-05',horizon_days:42,bucket:'week',default_calendar:'CAL',wacc:0.1,holding_spread:0.1},
  calendars:[{id:'CAL',workdays:[0,1,2,3,4]}],
  locations:[{id:'PUNE',type:'plant',name:'Pune plant'},{id:'FOUNDRY',type:'supplier',name:'Kolhapur foundry'}],
  products:[{id:'CASING',type:'RM',name:'Pump casing'}],
  location_products:[{location:'PUNE',product:'CASING',on_hand:0}],
  purchasing_sources:[{id:'PIR-CASING',supplier:'FOUNDRY',location:'PUNE',product:'CASING',price:1200,lead_time_days:3}],
  demand:[{id:'SO-88',location:'PUNE',product:'CASING',date:'2026-01-12',qty:120,kind:'sales_order'}],
  receipts:[{id:'PO-4501',kind:'purchase',location:'PUNE',product:'CASING',qty:120,due_date:'2026-01-19',source:'PIR-CASING'}],
};

test('rescheduling horizon: a late firm order is brought in instead of ordered again',async({page})=>{
  await imported(page,'Late Casing Pumps',lateCasing);
  await page.goto('/#/material/CASING/PUNE');      // importing plans it
  const list=page.getByRole('table');
  await expect(list.getByText('Firm purchase order PO-4501')).toBeVisible({timeout:45_000});
  await expect(list.getByText(/^Planned purchase PR-/)).toBeVisible();              // the duplicate
  await expect(page.getByText('Incoming order not needed')).toBeVisible();

  // ten working days of rescheduling horizon on the product's ordering view
  await page.getByRole('tab',{name:'Ordering',exact:true}).click();
  await page.getByLabel('Rescheduling horizon (working days)').fill('10');
  await page.getByRole('tab',{name:'Stock & requirements',exact:true}).click();
  const again=page.getByRole('button',{name:'Plan again',exact:true});
  await expect(again.or(page.getByText('Incoming order needed sooner'))).toBeVisible({timeout:45_000});
  if(await again.isVisible()) await again.click();
  await expect(page.getByText('Incoming order needed sooner')).toBeVisible({timeout:45_000});
  await expect(list.getByText(/^Planned purchase PR-/)).toHaveCount(0);
  await expect(list.getByText('Firm purchase order PO-4501')).toBeVisible();
  await expect(page.getByText('Incoming order not needed')).toHaveCount(0);

  // the Problems list says why, and what to do
  await page.goto('/#/plan');
  await expect(page.getByText('1 incoming order should arrive sooner')).toBeVisible({timeout:45_000});
});

// 2.2 (§6.2, fig. 6.2): a warehouse that takes a day to pick and pack and a day to load. Stock arrives on the 16th for
// a delivery on the 20th with 3 days on the road: shipped the day it arrives it would be on time, but it is there to
// pick on the 16th and leaves on the 18th, so the promise says the 21st, and why.
const slowDock={
  settings:{company_name:'Slow Dock Traders',planning_start:'2026-01-05',horizon_days:42,bucket:'week',default_calendar:'CAL',wacc:0.1,holding_spread:0.1},
  calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
  locations:[{id:'WH',type:'warehouse',name:'Bhiwandi warehouse',pick_pack_workdays:1,loading_workdays:1},
    {id:'MILL',type:'supplier',name:'Surat mill'},{id:'SAGAR',type:'customer',name:'Hotel Sagar'}],
  products:[{id:'TOWEL',type:'FG',name:'Bath towel',price:300}],
  location_products:[{location:'WH',product:'TOWEL',on_hand:0,mrp_type:'none'}],
  purchasing_sources:[{id:'PIR-TOWEL',supplier:'MILL',location:'WH',product:'TOWEL',price:180,lead_time_days:30}],
  lanes:[{id:'WH-SAGAR',origin:'WH',destination:'SAGAR',modes:[{transit_days:3}]}],
  receipts:[{id:'PO-77',kind:'purchase',location:'WH',product:'TOWEL',qty:50,due_date:'2026-01-16',source:'PIR-TOWEL'}],
  demand:[{id:'SO-501',location:'SAGAR',product:'TOWEL',date:'2026-01-20',qty:10,kind:'sales_order'}],
  promising:{include_planned_orders:false,confirm_beyond_rlt:false,ctp:false},
};

test('picking, packing and loading: the promise checks stock before the goods leave, and says so',async({page})=>{
  await imported(page,'Slow Dock Traders',slowDock);
  await page.goto('/#/promise/orders/SO-501');
  const lines=page.locator('table.t').filter({has:page.getByRole('columnheader',{name:'There to pick'})});
  await expect(lines).toBeVisible({timeout:45_000});
  await expect(lines.getByRole('columnheader',{name:'Leaves'})).toBeVisible();
  await expect(lines.locator('tbody tr').first()).toContainText(/16 Jan.*18 Jan.*21 Jan/);
  await expect(lines.locator('tbody tr').first()).toContainText('late');
  const why=page.getByRole('list',{name:'Why this date'});
  await expect(why.locator('li').nth(1)).toContainText(/18 Jan · Leaves Bhiwandi warehouse: picking, packing and loading take 2 working days/);

  // the warehouse's handling times are on the place itself
  await page.goto('/#/data/locations/WH');
  await expect(page.getByLabel('Picking and packing (working days)')).toHaveValue('1');
  await expect(page.getByLabel('Loading (working days)')).toHaveValue('1');
});
