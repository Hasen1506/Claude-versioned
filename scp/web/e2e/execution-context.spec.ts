import { expect, test, type Page } from '@playwright/test';

const fixture = (name: string) => ({
  settings: {company_name: name, planning_start: '2026-01-05', horizon_days: 28, default_calendar: 'CAL'},
  calendars: [{id: 'CAL', workdays: [0,1,2,3,4,5,6]}],
  locations: [{id: 'P', type: 'plant'}], products: [{id:'A', type:'FG'}],
  location_products: [{location:'P', product:'A', on_hand:10}],
  movements: [{id:'GM-00001', date:'2026-01-06', type:'receipt', location:'P', product:'A', qty:5}],
});

async function importCompany(page: Page, name: string) {
  await page.getByRole('button', {name:'More',exact:true}).click();
  const chooser = page.waitForEvent('filechooser');
  await page.getByRole('menuitem',{name:'Import a dataset file…'}).click();
  await (await chooser).setFiles({name:'fixture.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture(name)))});
  await expect(page.locator('.topbar .company')).toHaveText(name);
}

async function open(page: Page) {
  await page.goto('/');
  await page.getByRole('button',{name:'Start with an empty company'}).click();
  await page.getByLabel('Company name').fill('Context test');
  await page.getByRole('button',{name:'Create the company'}).click();
  await expect(page.getByRole('heading',{name:'Set up your company'})).toBeVisible();
  await importCompany(page,'Company A');
  await page.goto('/#/execution/roll');
}

test('roll report follows its dataset through tab navigation and disappears on undo or company switch',async ({page})=>{
  await open(page);
  await page.getByRole('button',{name:'Move the plan to this date'}).click();
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toBeVisible();
  await page.goto('/#/execution/journal');
  await page.goto('/#/execution/roll');
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toBeVisible();
  await page.getByRole('button',{name:'Undo',exact:true}).click();
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toHaveCount(0);
  await page.getByRole('button',{name:'Redo',exact:true}).click();
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toBeVisible();
  await importCompany(page,'Company B');
  await page.goto('/#/execution/roll');
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toHaveCount(0);
  await expect(page.getByLabel('Roll forward to')).toHaveValue('2026-01-12');
  await page.screenshot({path:test.info().outputPath('company-b-clean-roll.png'),fullPage:true});
});

test('a delayed roll cannot replace a company opened while it was running',async ({page})=>{
  await open(page);
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested!:()=>void;
  const arrived=new Promise<void>(resolve=>{requested=resolve;});
  await page.route('**/api/actuals/roll',async route=>{
    const response=await route.fetch(); requested(); await gate; await route.fulfill({response});
  });
  await page.getByRole('button',{name:'Move the plan to this date'}).click();
  await arrived;
  await importCompany(page,'Company B');
  const answer=page.waitForResponse('**/api/actuals/roll');
  release();
  await (await answer).finished();
  await page.goto('/#/execution/roll');
  await expect(page.getByLabel('Roll forward to')).toHaveValue('2026-01-12');
  // A visible completion from the old company is also forbidden.
  await expect(page.getByText('Rolled from Mon 5 Jan to Mon 12 Jan')).toHaveCount(0);
  await expect(page.locator('.topbar .company')).toHaveText('Company B');
  await page.reload();
  await expect(page.locator('.topbar .company')).toHaveText('Company B');
  await expect(page.getByLabel('Roll forward to')).toHaveValue('2026-01-12');
});

test('an edit made during a roll survives the delayed response',async ({page})=>{
  await open(page);
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  let requested!:()=>void;
  const arrived=new Promise<void>(resolve=>{requested=resolve;});
  await page.route('**/api/actuals/roll',async route=>{
    const response=await route.fetch(); requested(); await gate; await route.fulfill({response});
  });
  await page.getByRole('button',{name:'Move the plan to this date'}).click();
  await arrived;
  await page.goto('/#/data/location_products/P%7CA');
  await page.locator('input[id="on_hand"]').fill('25');
  await page.locator('input[id="on_hand"]').press('Enter');
  const answer=page.waitForResponse('**/api/actuals/roll');
  release();
  await (await answer).finished();
  await expect(page.locator('input[id="on_hand"]')).toHaveValue('25');
  await page.reload();
  await expect(page.locator('input[id="on_hand"]')).toHaveValue('25');
  await page.screenshot({path:test.info().outputPath('kept-edit.png'),fullPage:true});
  await page.goto('/#/execution/roll');
  await expect(page.getByLabel('Roll forward to')).toHaveValue('2026-01-12');
});
