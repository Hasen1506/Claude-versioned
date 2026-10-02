import { expect, test, type Page } from '@playwright/test';

// Phase P: levelling by hand on the Capacity page. Two runs want the one 8 h machine on the same day; one is moved
// with its date field (keyboard, phone), the other dragged onto a day square; each becomes a firm run on its new day.
function fixture() {
  return {
    settings:{company_name:'Levelling by hand',planning_start:'2026-01-05',horizon_days:28,default_calendar:'CAL',wacc:0,holding_spread:0},
    calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
    locations:[{id:'P',type:'plant'},{id:'S',type:'supplier'}],
    products:[{id:'A',type:'FG'},{id:'D',type:'FG'},{id:'B',type:'RM'},{id:'C',type:'RM'}],
    location_products:[{location:'P',product:'A',on_hand:0},{location:'P',product:'D',on_hand:0},
      {location:'P',product:'B',on_hand:1000},{location:'P',product:'C',on_hand:1000}],
    resources:[{id:'M1',name:'Press 1',location:'P',hours_per_shift:8,efficiency:1,cost_per_hour:100,overtime_hours_per_day:4,overtime_cost_per_hour:50}],
    production_sources:['A','D'].map(p=>({id:`PV-${p}`,location:'P',product:p,components:[{product:'B',qty:2},{product:'C',qty:1}],
      operations:[{seq:10,resource:'M1',setup_hours:0,run_hours_per_unit:0.5}]})),
    purchasing_sources:[{id:'PIR-B',supplier:'S',location:'P',product:'B',price:10,lead_time_days:3},{id:'PIR-C',supplier:'S',location:'P',product:'C',price:5,lead_time_days:1}],
    demand:[{location:'P',product:'A',date:'2026-01-12',qty:16,kind:'forecast'},{location:'P',product:'D',date:'2026-01-12',qty:16,kind:'forecast'}],
  };
}

async function open(page:Page) {
  await page.goto('/');
  const chooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'Import a file',exact:true}).click();
  await (await chooser).setFiles({name:'levelling.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture()))});
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({timeout:45000});
}

const square=(page:Page,label:RegExp)=>page.getByRole('group',{name:'Days'}).getByRole('button',{name:label});

test('levelling by hand: move a run with its date, drag another onto a day, both stay firm there; overtime is a choice',async ({page})=>{
  await open(page);
  await page.goto('/#/capacity');
  await expect(page.locator('.stage-head .answer')).toContainText(/asked for more than it has on 1 day/);
  // the day squares open a day's orders without a mouse on the chart
  await square(page,/^[A-Z][a-z]{2} 11 Jan: 16 of 8 h/).click();
  await expect(page.getByRole('heading',{name:/Orders on Press 1, .*11 Jan/})).toBeVisible();
  const fields=page.getByLabel(/^Move .+ to$/);
  await expect(fields).toHaveCount(2);
  // one run moved a day earlier with its date field
  const first=(await fields.first().getAttribute('aria-label'))!.replace(/^Move | to$/g,'');
  await fields.first().fill('2026-01-10');
  await page.getByRole('button',{name:/^Move to .*10 Jan/}).click();
  await expect(page.getByText(new RegExp(`${first} is now PRD-00001, a firm run starting .*10 Jan`))).toBeVisible({timeout:45000});
  await expect(square(page,/^[A-Z][a-z]{2} 11 Jan: 8 of 8 h/)).toBeVisible({timeout:45000});
  await expect(square(page,/^[A-Z][a-z]{2} 10 Jan: 8 of 8 h/)).toBeVisible();
  // the other dragged onto two days earlier; 11 Jan stays open after the move, now with one run
  await expect(square(page,/^[A-Z][a-z]{2} 11 Jan: 8 of 8 h/)).toHaveAttribute('aria-pressed','true');
  const row=page.getByRole('row').filter({has:page.getByLabel(/^Move .+ to$/)});
  await expect(row).toHaveCount(1);
  await row.dragTo(square(page,/^[A-Z][a-z]{2} 9 Jan: 0 of 8 h/));
  await page.getByRole('button',{name:/^Move to .*9 Jan/}).click();
  await expect(page.getByText(/is now PRD-00002, a firm run starting .*9 Jan/)).toBeVisible({timeout:45000});
  await expect(square(page,/^[A-Z][a-z]{2} 9 Jan: 8 of 8 h/)).toBeVisible({timeout:45000});
  await expect(square(page,/^[A-Z][a-z]{2} 11 Jan: 0 of 8 h/)).toBeVisible();
  await expect(page.locator('.stage-head .answer')).toContainText(/No machine or crew is asked for more hours than it has/);
  // overtime is a levelling choice
  const ot=page.getByLabel('Levelling may plan overtime');
  await expect(ot).not.toBeChecked();
  await ot.check();
  await expect(ot).toBeChecked();
});
