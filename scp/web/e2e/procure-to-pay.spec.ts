import { expect, test, type Page } from '@playwright/test';

// Phase N: procure to pay on the Buying page. Firming makes a purchase order priced from a contract and offers to send
// it (R20); it waits for two release levels first. The supplier confirms it in two deliveries, the first arrives,
// the invoice comes in over the order's price and is blocked, released and paid with the cash discount; five tins go
// back and are credited; what is owed shows the credit; a scheduling agreement is made for the next purchases.
function fixture() {
  return {
    settings:{company_name:'Procure to pay',company_address:'Plot 4, MIDC\nPune',planning_start:'2026-01-05',horizon_days:28,default_calendar:'CAL',wacc:0,holding_spread:0},
    calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
    locations:[{id:'PUNE',name:'Pune plant',type:'plant'},{id:'SHARMA',name:'Sharma Metals',type:'supplier',address:'Bhosari\nPune'}],
    products:[{id:'TIN',name:'Tin of white',type:'FG',price:100}],
    location_products:[{location:'PUNE',product:'TIN',on_hand:0,lot_sizing:{policy:'L4L'}}],
    purchasing_sources:[{id:'PIR-TIN',supplier:'SHARMA',location:'PUNE',product:'TIN',price:10,lead_time_days:3}],
    payment_terms:[{id:'2-10-30',name:'2 % 10 days, net 30',net_days:30,discount_days:10,discount:0.02}],
    vendors:[{supplier:'SHARMA',payment_terms:'2-10-30',email:'sales@sharma.example'}],
    contracts:[{id:'CT-00001',supplier:'SHARMA',valid_from:'2026-01-01',valid_to:'2026-03-31',lines:[{product:'TIN',price:9,target_qty:500}]}],
    purchasing:{tax_rate:0.1,release_levels:[{name:'Buyer',above:500},{name:'Director',above:1000}]},
    demand:[{id:'SO-1',location:'PUNE',product:'TIN',date:'2026-01-12',qty:120,kind:'sales_order'}],
  };
}

async function open(page:Page) {
  await page.goto('/');
  const chooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'Import a file',exact:true}).click();
  await (await chooser).setFiles({name:'p2p.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture()))});
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({timeout:45000});
}

const done=(page:Page)=>page.locator('.banner[role="status"]').last();

test('procure to pay: firmed and sent, released at two levels, confirmed in two deliveries, invoiced, blocked, paid, partly returned and credited',async ({page})=>{
  test.setTimeout(240000);
  await open(page);

  // firming makes the purchase order and offers to send it; above two release levels it waits
  await page.goto('/#/execution/orders');
  const calculate=page.getByRole('button',{name:/^(Recalculate the supply plan|Calculate the supply plan)$/});
  // pages load on demand: wait for the firm zone to be drawn before asking whether the plan needs calculating
  await expect(page.getByRole('heading',{name:/^Firm zone:/})).toBeVisible({timeout:45000});
  if(await calculate.count()) await calculate.click();
  await page.getByRole('button',{name:'Make 1 order firm',exact:true}).click();
  await expect(done(page)).toContainText(/1 planned order firmed.*PO-00001/,{timeout:45000});
  await page.getByRole('button',{name:'Send the 1 purchase order now'}).click();
  await expect(done(page)).toContainText(/PO-00001 waits to be released first/,{timeout:45000});

  // released by the buyer, then the director, then sent
  await page.goto('/#/buying/orders/PO-00001');
  await expect(page.getByText(/Needs Buyer, then Director/)).toBeVisible({timeout:45000});
  await expect(page.getByText(/contract CT-00001/).first()).toBeVisible();
  await page.getByRole('button',{name:'Release: Buyer'}).click();
  await expect(done(page)).toContainText('PO-00001 released at level Buyer; still to be released by Director',{timeout:45000});
  await page.getByRole('button',{name:'Release: Director'}).click();
  await expect(done(page)).toContainText(/fully released, it can be sent/,{timeout:45000});
  await page.getByRole('button',{name:'Mark as sent'}).click();
  await expect(done(page)).toContainText(/PO-00001 sent to Sharma Metals/,{timeout:45000});

  // confirmed in two deliveries
  await page.getByRole('button',{name:'Record confirmation'}).click();
  await page.getByRole('button',{name:'Several deliveries'}).click();
  await page.getByLabel('Delivery 1 quantity PO-00001-10').fill('70');
  await page.getByLabel('Delivery 1 date PO-00001-10').fill('2026-01-08');
  await page.getByLabel('Delivery 2 quantity PO-00001-10').fill('50');
  await page.getByLabel('Delivery 2 date PO-00001-10').fill('2026-01-10');
  await page.getByRole('button',{name:'Save confirmation'}).click();
  await expect(done(page)).toContainText(/PO-00001-10 in 2 deliveries \(70 on .*, 50 on .*\)/,{timeout:45000});

  // the first 70 arrive
  await page.getByRole('button',{name:'Receive goods'}).click();
  await page.getByLabel('Receive quantity PO-00001-10').fill('70');
  await page.getByRole('button',{name:'Post goods receipt'}).click();
  await expect(done(page)).toContainText(/Goods received on PO-00001/,{timeout:45000});

  // the invoice bills them at 9.50 against the contract's 9: blocked, released, paid in time for the discount
  await page.getByRole('button',{name:'Enter the invoice'}).click();
  await expect(page.getByLabel('Billed quantity PO-00001-10')).toHaveAttribute('placeholder','70');
  await page.getByLabel('Their invoice number').fill('INV-9');
  await page.getByLabel('Billed price PO-00001-10').fill('9.5');
  await page.getByRole('button',{name:/^Enter the invoice \(₹731.50\)/}).click();
  await expect(done(page)).toContainText(/SI-00001 from Sharma Metals \(their INV-9\): INR 731.50, 1 line; blocked for payment: PO-00001-10 invoiced at 9.50, the order says 9.00/,{timeout:45000});
  await page.getByRole('row',{name:/SI-00001/}).click();
  await expect(page.getByText('Blocked for payment:')).toBeVisible();
  await page.getByRole('button',{name:'Release for payment'}).click();
  await expect(done(page)).toContainText(/SI-00001 released for payment/,{timeout:45000});
  await expect(page.getByLabel('Amount paid')).toHaveAttribute('placeholder','716.87');
  await page.getByLabel('Bank reference').fill('NEFT-1');
  await page.getByRole('button',{name:/^Pay ₹716.87/}).click();
  await expect(done(page)).toContainText('INR 716.87 paid on SI-00001, cash discount INR 14.63; settled.',{timeout:45000});
  await page.screenshot({path:'test-results/buying-invoice.png',fullPage:true});

  // the supplier later credits 0.30 a tin on the 70 invoiced (N132): a subsequent credit, the quantity invoiced unchanged
  await page.getByText('Price put right later').click();
  await page.getByLabel('Charge or credit').selectOption('subsequent_credit');
  await page.getByLabel('Difference per unit').fill('0.3');
  await expect(page.getByLabel('Units corrected')).toHaveAttribute('placeholder','70');
  await page.getByLabel('Their debit or credit note number').fill('CN-3');
  await page.getByRole('button',{name:/^Enter the credit \(₹21.00 before tax\)/}).click();
  await expect(done(page)).toContainText('Subsequent credit SC-00001 from Sharma Metals (their CN-3): INR 23.10 (less per unit: PO-00001-10 0.30 on 70).',{timeout:45000});
  await expect(page.getByRole('row',{name:/SC-00001.*subsequent credit/})).toContainText('−₹23.10');

  // five tins go back and are credited at the 9.20 they cost after the credit
  await page.goto('/#/buying/returns');
  await page.getByLabel('Order line sent back').selectOption('PO-00001-10');
  await page.getByLabel('Quantity sent back').fill('5');
  await page.getByLabel('Stock it leaves').selectOption('unrestricted');
  await page.getByLabel('Why it goes back').fill('dented');
  await page.getByRole('button',{name:'Send them back'}).click();
  await expect(done(page)).toContainText(/Return RS-00001: 5 of Tin of white sent back to Sharma Metals from Pune plant .*\(dented\)\. PO-00001-10 is now for 115; a credit memo is expected/,{timeout:45000});
  await page.getByLabel('Credit memo number for RS-00001').fill('CN-4');
  await page.getByRole('button',{name:'Credit memo in'}).click();
  await expect(done(page)).toContainText('Credit memo CM-00001 from Sharma Metals (their CN-4): INR 50.60 for return RS-00001.',{timeout:45000});
  await expect(page.getByRole('row',{name:/RS-00001.*credited/})).toBeVisible();

  // what we owe Sharma: the two credits
  await page.goto('/#/buying/owed');
  await expect(page.getByRole('row',{name:/Sharma Metals/})).toContainText('−₹73.70');

  // the contract counts what was ordered
  await page.goto('/#/buying/contracts');
  await expect(page.getByRole('row',{name:/CT-00001/})).toContainText('115');

  // a scheduling agreement for the next purchases
  await page.goto('/#/buying/suppliers');
  await page.getByRole('row',{name:/Sharma Metals/}).click();
  await page.getByRole('button',{name:'Make one'}).click();
  await expect(done(page)).toContainText(/Scheduling agreement SA-00001: Tin of white from Sharma Metals to Pune plant at 9.00 \(contract CT-00001\)/,{timeout:45000});
  await page.screenshot({path:'test-results/buying-supplier.png',fullPage:true});

  // every tab fits a phone: nothing scrolls sideways
  await page.setViewportSize({width:390,height:800});
  for (const tab of ['order','orders/PO-00001','invoices/SI-00001','owed','returns','contracts','suppliers']) {
    await page.goto(`/#/buying/${tab}`);
    await expect(page.locator('.content')).toBeVisible();
    const wide=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
    expect(wide,`#/buying/${tab} scrolls sideways`).toBeLessThanOrEqual(1);
  }
  await page.screenshot({path:'test-results/buying-phone.png',fullPage:true});
});
