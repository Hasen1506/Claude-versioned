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
