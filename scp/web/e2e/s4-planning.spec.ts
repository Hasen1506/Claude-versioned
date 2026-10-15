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

// 2.3 (§8.5): a casing with a 10-day fence (to Thu 15 Jan). Type 3, the default, moves the order for the 12th to the
// fence end; type 4 plans nothing inside the fence, says so, and covers it at the first check beyond it (Mon 19 Jan)
test('firming type 4: nothing planned inside the fence, and the shortage is said',async({page})=>{
  const fenced={...lateCasing,settings:{...lateCasing.settings,company_name:'Fenced Casing Pumps'},receipts:[],
    location_products:[{location:'PUNE',product:'CASING',on_hand:0,planning_time_fence_days:10}]};
  await imported(page,'Fenced Casing Pumps',fenced);
  await page.goto('/#/material/CASING/PUNE');
  const planned=page.getByRole('row').filter({hasText:/Planned purchase PR-/});
  await expect(planned).toHaveCount(1,{timeout:45_000});
  await expect(planned).toContainText('Thu 15 Jan');
  await page.getByRole('tab',{name:'Ordering',exact:true}).click();
  await page.getByLabel('Firming type (1–4)').fill('4');
  await page.getByRole('tab',{name:'Stock & requirements',exact:true}).click();
  const again=page.getByRole('button',{name:'Plan again',exact:true});
  await expect(again.or(page.getByText('Short inside the freeze window'))).toBeVisible({timeout:45_000});
  if(await again.isVisible()) await again.click();
  await expect(page.getByText('Short inside the freeze window')).toBeVisible({timeout:45_000});
  await expect(planned).toHaveCount(1);
  await expect(planned).toContainText('Mon 19 Jan');
  await page.goto('/#/plan');
  await expect(page.getByText('1 product short inside the freeze window')).toBeVisible({timeout:45_000});
});

// 2.4 (§8.7): a casing positioned as a DDMRP buffer (10 a day, 10 days to buy, weekly CV 0.2: TOR 87.5, TOY 187.5,
// TOG 257.5) with 120 on hand. As advice only the screen says so; once the buffer plans the orders, the plan buys
// TOG − NFP = 147.5 (148 whole) today and the Problems list asks for it
test('DDMRP buffer: from advice beside MRP to the buffer placing the orders',async({page})=>{
  const buffered={...lateCasing,settings:{...lateCasing.settings,company_name:'Buffered Casing Pumps',bucket:'week'},
    calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],receipts:[],
    location_products:[{location:'PUNE',product:'CASING',on_hand:120,ddmrp_buffer:true,safety_stock:{demand_cv:0.2}}],
    purchasing_sources:[{...lateCasing.purchasing_sources[0],lead_time_days:10}],
    demand:Array.from({length:42},(_,i)=>({id:`SO-${i+1}`,location:'PUNE',product:'CASING',kind:'sales_order',qty:10,
      date:new Date(Date.UTC(2026,0,5+i)).toISOString().slice(0,10)}))};
  await imported(page,'Buffered Casing Pumps',buffered);
  await page.goto('/#/inventory/ddmrp');
  await page.getByRole('button',{name:'Recalculate',exact:true}).click();
  const row=page.getByRole('row').filter({hasText:'Pump casing'});
  await expect(row).toContainText('yellow',{timeout:45_000});
  await expect(row).toContainText(/110yellow.*148/);       // NFP 110, order 148 (147.5 in whole casings)
  await expect(page.getByText('Advice only')).toBeVisible();

  await page.getByLabel('Let the buffer of Pump casing at Pune plant place the orders').check();
  await expect(page.getByText('Advice only')).toHaveCount(0);

  await page.goto('/#/material/CASING/PUNE');
  const again=page.getByRole('button',{name:'Plan again',exact:true});
  const planned=page.getByRole('row').filter({hasText:/Planned purchase PR-/});
  // the plan from before the tick may still be on screen, with Plan again offered now or a moment later
  await expect(async()=>{
    if(await again.isVisible()) await again.click();
    await expect(planned.first()).toContainText('Mon 5 Jan',{timeout:2_000});
  }).toPass({timeout:45_000});
  await expect(planned.first()).toContainText('148');
  await page.goto('/#/plan');
  await expect(page.getByText('1 buffer to reorder today')).toBeVisible({timeout:45_000});
});

// 2.5 (§16.2): casings bought to order. PO-1 (50, due 14 Jan) was bought for SO-1 (20 Jan); SO-2 wants 50 on the 12th,
// and a new order takes 10 days. 20 casings in stock are held for SO-3. Free, PO-1 would go to SO-2; held, it stays
// with SO-1, the plan buys for SO-2, the promise says SO-1 is served from what is held for it, and the stock page
// shows the held 20 apart from the free stock
test('sales-order stock: supply held for one order is planned, promised and shown for it alone',async({page})=>{
  const mto={...lateCasing,settings:{...lateCasing.settings,company_name:'Bespoke Casing Pumps'},
    location_products:[{location:'PUNE',product:'CASING',on_hand:0,strategy:'MTO',order_stock:[{order:'SO-3',qty:20}]}],
    purchasing_sources:[{...lateCasing.purchasing_sources[0],lead_time_days:10}],
    demand:[{id:'SO-1',location:'PUNE',product:'CASING',date:'2026-01-20',qty:50,kind:'sales_order'},
      {id:'SO-2',location:'PUNE',product:'CASING',date:'2026-01-12',qty:50,kind:'sales_order'},
      {id:'SO-3',location:'PUNE',product:'CASING',date:'2026-01-22',qty:20,kind:'sales_order'}],
    receipts:[{id:'PO-1',kind:'purchase',location:'PUNE',product:'CASING',qty:50,due_date:'2026-01-14',source:'PIR-CASING',sales_order:'SO-1'}],
    promising:{include_planned_orders:false,confirm_beyond_rlt:false,ctp:false}};
  await imported(page,'Bespoke Casing Pumps',mto);
  await page.goto('/#/material/CASING/PUNE');
  // the free stock: SO-2 is 50 short on the 12th (the 20 held for SO-3 do not soften it), and bought for
  await expect(page.getByText('Stock runs out on Mon 12 Jan (-50)')).toBeVisible({timeout:45_000});
  await expect(page.getByRole('row').filter({hasText:/Planned purchase PR-/})).toContainText('for SO-2');
  await expect(page.getByText('Incoming order needed sooner')).toHaveCount(0);
  // what is held, order by order
  const held=page.locator('.panel',{has:page.getByRole('heading',{name:'Held for sales orders (2)'})});
  await expect(held.getByRole('row').filter({hasText:'Firm purchase order PO-1'})).toContainText('+50');
  await expect(held.getByRole('row').filter({hasText:'Customer order SO-1'})).toContainText('-50');
  await expect(held.getByRole('row').filter({hasText:'In stock, held for this order'})).toContainText('SO-3');

  await page.goto('/#/promise/orders/SO-1');
  const why=page.getByRole('list',{name:'Why this date'});
  await expect(why).toContainText('Firm receipt PO-1 brings 50 to Pune plant, held for this order',{timeout:45_000});

  await page.goto('/#/execution');
  await expect(page.getByText('20 held for SO-3')).toBeVisible({timeout:45_000});
});

// 2.6 (§13, §15, §18.2): 40 casings at Pune. SO-0 (10, asked for Fri 2 Jan, so late) and SO-1 (30) take them; SO-2
// (30) finds none to pick. The imported lines carry no price: the casing's price is fixed when they ship, and the
// OTIF note says what is late and not shipped yet.
test('a delivery takes only what can be picked, the price is fixed when the goods leave, late open lines are counted',async({page})=>{
  const short={settings:{company_name:'Short Casing Pumps',planning_start:'2026-01-05',horizon_days:28,bucket:'week',default_calendar:'CAL'},
    calendars:[{id:'CAL',workdays:[0,1,2,3,4]}],
    locations:[{id:'PUNE',type:'plant',name:'Pune plant'},{id:'KUMAR',type:'customer',name:'Kumar Pumps'}],
    lanes:[{id:'PUNE-KUMAR',origin:'PUNE',destination:'KUMAR',modes:[{transit_days:1}]}],
    products:[{id:'CASING',type:'FG',name:'Pump casing',price:1500}],
    location_products:[{location:'PUNE',product:'CASING',on_hand:40}],
    demand:[{id:'SO-0',location:'KUMAR',product:'CASING',date:'2026-01-02',qty:10,kind:'sales_order'},
      {id:'SO-1',location:'KUMAR',product:'CASING',date:'2026-01-06',qty:30,kind:'sales_order'},
      {id:'SO-2',location:'KUMAR',product:'CASING',date:'2026-01-07',qty:30,kind:'sales_order'}]};
  await imported(page,'Short Casing Pumps',short);
  const done=page.locator('.banner').last();

  // the late backlog is in the OTIF note before anything ships
  await page.goto('/#/tower');
  await page.getByRole('button',{name:'Calculate',exact:true}).click();
  await page.getByRole('button',{name:/^OTIF to requested date:/}).click({timeout:45_000});
  await page.locator('.reading summary',{hasText:'How this is calculated'}).click();
  await expect(page.getByText(/Not in this figure: 1 open order line worth INR 15,000 already past the requested date/)).toBeVisible({timeout:45_000});

  // what can be picked, first to ship first served
  await page.goto('/#/selling/deliver');
  await page.getByRole('button',{name:'Calculate',exact:true}).click();
  await expect(page.getByRole('row',{name:/SO-2/})).toContainText('none in stock',{timeout:45_000});
  await expect(page.getByLabel('Deliver SO-2')).not.toBeChecked();
  await expect(page.getByRole('row',{name:/SO-1/})).not.toContainText('only');
  await page.screenshot({path:'test-results/delivery-check.png',fullPage:true});
  await page.getByLabel('Deliver SO-2').check();
  await page.getByRole('button',{name:/Make deliveries for 3 lines/}).click();
  await expect(done).toContainText(/Not enough in stock: SO-2: nothing of 30 can be picked \(Pump casing at Pune plant by Mon 5 Jan\), it stays to deliver/,{timeout:45_000});
  await expect(page.getByRole('row',{name:/SO-2/})).toContainText('none in stock');

  // shipped: the price the lines had none of is fixed
  await page.getByRole('row',{name:/DL-00001/}).click();
  await page.getByRole('button',{name:'Ship it'}).click();
  await expect(done).toContainText(/SO-1 had no agreed price: INR 1,500.00 a unit fixed at goods issue/,{timeout:45_000});
});
