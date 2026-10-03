import { expect, test, type Page } from '@playwright/test';

// Phase M: order to cash on the Selling page. An order of two lines priced by a scale and the customer's discount goes
// over the credit limit and is released; it is delivered (picked short, packed, shipped, signed for), invoiced and
// paid with the cash discount; one tin comes back and is credited; a quotation is won.
function fixture() {
  return {
    settings:{company_name:'Order to cash',company_address:'Plot 4, MIDC\nPune',planning_start:'2026-01-05',horizon_days:28,default_calendar:'CAL',wacc:0,holding_spread:0},
    calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
    locations:[{id:'P',name:'Pune plant',type:'plant'},{id:'S',name:'Supplier',type:'supplier'},{id:'K',name:'Kumar Stores',type:'customer',address:'MG Road\nMumbai'}],
    products:[{id:'A',name:'Tin of white',type:'FG',price:100},{id:'D',name:'Drum of thinner',type:'FG',price:20}],
    location_products:[{location:'P',product:'A',on_hand:100},{location:'P',product:'D',on_hand:50}],
    purchasing_sources:[{id:'PIR-A',supplier:'S',location:'P',product:'A',price:60,lead_time_days:5},{id:'PIR-D',supplier:'S',location:'P',product:'D',price:12,lead_time_days:5}],
    lanes:[{id:'PK',origin:'P',destination:'K',modes:[{transit_days:1}]}],
    customer_prices:[{customer:'K',product:'A',price:90,scales:[{from_qty:20,price:80}]}],
    payment_terms:[{id:'2-10-30',name:'2 % 10 days, net 30',net_days:30,discount_days:10,discount:0.02}],
    customers:[{customer:'K',payment_terms:'2-10-30',discount:0.05,credit_limit:1000,tax_rate:0.1,email:'buy@kumar.example'}],
    demand:[],
  };
}

async function open(page:Page) {
  await page.goto('/');
  const chooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'Import a file',exact:true}).click();
  await (await chooser).setFiles({name:'o2c.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture()))});
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({timeout:45000});
}

const done=(page:Page)=>page.locator('.banner[role="status"]').last();

test('order to cash: a two-line order over the credit limit is released, delivered, invoiced, paid, partly returned and credited; a quotation is won',async ({page})=>{
  test.setTimeout(240000);
  await open(page);
  await page.goto('/#/selling/new');
  // two lines: 25 tins reach the 20+ scale (80, less 5 %), 10 drums at the product's 20 less 5 %
  await page.getByLabel('Line 10 product').selectOption('A');
  await page.getByLabel('Line 10 quantity').fill('25');
  await page.getByLabel('Line 10 wanted on').fill('2026-01-08');
  await expect(page.getByLabel('Line 10 price')).toHaveAttribute('placeholder','76');
  await page.getByRole('button',{name:'+ Add a line'}).click();
  await page.getByLabel('Line 20 product').selectOption('D');
  await page.getByLabel('Line 20 quantity').fill('10');
  await page.getByLabel('Line 20 wanted on').fill('2026-01-08');
  await page.getByLabel('Their order number').fill('PO-77');
  await page.getByRole('button',{name:'Take the order'}).click();
  await expect(done(page)).toContainText(/SO-00001 taken for Kumar Stores: 2 lines, INR 2,299.00 with tax/,{timeout:45000});
  await expect(done(page)).toContainText(/Blocked for delivery/);

  // the order is held until released
  await page.goto('/#/selling/orders/SO-00001');
  await expect(page.getByText(/It is promised but cannot ship until released/)).toBeVisible({timeout:45000});
  await page.getByRole('button',{name:'Release for delivery'}).click();
  await expect(done(page)).toContainText('SO-00001 released for delivery.',{timeout:45000});
  await page.getByRole('button',{name:'Mark as sent'}).click();
  await expect(done(page)).toContainText(/Order confirmation SO-00001 sent to Kumar Stores/,{timeout:45000});
  await page.screenshot({path:'test-results/selling-order.png',fullPage:true});

  // delivered: picked two drums short, packed, shipped, signed for
  await page.goto('/#/selling/deliver');
  await page.getByRole('button',{name:/Make deliveries for 2 lines/}).click();
  await expect(done(page)).toContainText(/DL-00001 to Kumar Stores from Pune plant: 2 lines/,{timeout:45000});
  await page.getByRole('row',{name:/DL-00001/}).click();
  await page.getByLabel('Picked on SO-00001/20').fill('8');
  await page.getByRole('button',{name:'Picked',exact:true}).click();
  await expect(done(page)).toContainText(/SO-00001\/20 8 of 10/,{timeout:45000});
  await page.getByLabel('Packages').fill('3');
  await page.getByRole('button',{name:'Packed'}).click();
  await expect(done(page)).toContainText(/DL-00001 packed: 3 packages/,{timeout:45000});
  await page.getByRole('button',{name:'Ship it'}).click();
  await expect(done(page)).toContainText(/DL-00001 shipped to Kumar Stores/,{timeout:45000});
  await page.screenshot({path:'test-results/selling-delivery.png',fullPage:true});
  await page.getByLabel('Signed by').fill('R. Kumar');
  await page.getByRole('button',{name:'Signed for'}).click();
  await expect(done(page)).toContainText(/DL-00001 delivered on .* signed by R. Kumar/,{timeout:45000});
  // the two drums not picked are still due
  await expect(page.getByRole('row',{name:/SO-00001\/20.*Drum of thinner.*2/})).toBeVisible();

  // invoiced and paid within ten days: the cash discount is taken
  await page.goto('/#/selling/bill');
  await page.getByRole('button',{name:/^Invoice ₹2,052.00/}).click();
  await expect(done(page)).toContainText(/INV-00001 to Kumar Stores: INR 2,257.20 due/,{timeout:45000});
  await page.getByRole('row',{name:/INV-00001/}).click();
  await expect(page.getByLabel('Amount')).toHaveValue('2212.06');
  await page.getByRole('button',{name:'Payment received'}).click();
  await expect(done(page)).toContainText(/INR 2,212.06 received for INV-00001.*cash discount INR 45.14; settled/,{timeout:45000});

  // one tin comes back and is credited
  await page.goto('/#/selling/returns');
  await page.getByLabel('Order line returned').selectOption('SO-00001/10');
  await page.getByLabel('Why it comes back').fill('dented');
  await page.getByRole('button',{name:'Agree the return'}).click();
  await expect(done(page)).toContainText(/Return RET-00001: 1 Tin of white from Kumar Stores expected at Pune plant/,{timeout:45000});
  await page.getByRole('button',{name:'Goods are back'}).click();
  await expect(done(page)).toContainText(/into quality inspection/,{timeout:45000});
  await page.getByRole('button',{name:'Credit it'}).click();
  await expect(done(page)).toContainText(/Credit note CN-00001 for Kumar Stores: INR 83.60 against INV-00001/,{timeout:45000});

  // what Kumar owes: the two drums still open
  await page.goto('/#/selling/customers');
  await expect(page.getByRole('row',{name:/Kumar Stores/})).toContainText('₹1,000');

  // a quotation, won: an order at the quoted price
  await page.goto('/#/selling/new');
  await page.getByLabel('Line 10 product').selectOption('A');
  await page.getByLabel('Line 10 quantity').fill('5');
  await page.getByLabel('Line 10 price').fill('70');
  await page.getByRole('button',{name:'Make a quotation'}).click();
  await expect(done(page)).toContainText(/Quotation QT-00001 for Kumar Stores: 1 line, INR 350.00 before tax/,{timeout:45000});
  await page.goto('/#/selling/quotes');
  await page.getByRole('button',{name:'Won: make the order'}).click();
  await expect(done(page)).toContainText(/QT-00001 won. SO-00002 taken for Kumar Stores/,{timeout:45000});

  // every tab fits a phone: nothing scrolls sideways
  await page.setViewportSize({width:390,height:800});
  for (const tab of ['orders/SO-00001','new','quotes','deliver/DL-00001','bill/INV-00001','returns','customers']) {
    await page.goto(`/#/selling/${tab}`);
    await expect(page.locator('.content')).toBeVisible();
    const wide=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
    expect(wide,`#/selling/${tab} scrolls sideways`).toBeLessThanOrEqual(1);
  }
  await page.screenshot({path:'test-results/selling-phone.png',fullPage:true});
});

test('tax per product with the GST split (N123): the invoice shows CGST and SGST per rate, the total as the server bills it',async ({page})=>{
  const f:any=fixture();
  f.settings.company_tax_id='27AAACM1234A1Z5';
  f.locations[2].tax_id='27AAFCK9876B1Z2';
  f.customers[0].tax_rate=null;
  f.products[1].tax_rate=0.12;
  f.sales={tax_rate:0.18,tax_split:'gst'};
  f.invoices=[{id:'INV-00001',customer:'K',date:'2026-01-05',due_date:'2026-02-04',tax_rate:0.18,tax_split:'cgst_sgst',
    lines:[{product:'A',qty:25,price:76},{product:'D',qty:10,price:19,tax_rate:0.12}]}];
  await page.goto('/');
  const chooser=page.waitForEvent('filechooser');
  await page.getByRole('button',{name:'Import a file',exact:true}).click();
  await (await chooser).setFiles({name:'gst.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(f))});
  await expect(page.getByText(/Everything is up to date/)).toBeVisible({timeout:45000});
  await page.goto('/#/selling/bill/INV-00001');
  await expect(page.getByRole('row',{name:/INV-00001/})).toContainText('₹2,454.80',{timeout:45000});
  const [dl]=await Promise.all([page.waitForEvent('download'),page.getByRole('button',{name:'Download'}).first().click()]);
  const fs=await import('node:fs');
  const html=fs.readFileSync((await dl.path())!,'utf8');
  for (const t of ['CGST 6 %','SGST 6 %','CGST 9 %','SGST 9 %','on ₹1,900.00','on ₹190.00','₹171.00','₹11.40','₹2,454.80','tax 12 %'])
    expect(html,t).toContain(t);
  expect(html).not.toContain('IGST');
});
