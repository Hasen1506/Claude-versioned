import {createHmac} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {expect,test,type Page} from '@playwright/test';

// ENTERPRISE_PLAN 1.3: two-step sign-in through the screens: turn it on with an authenticator app's code, keep the
// recovery codes, sign out, sign in with the password and then the app's code, and require it of a company's members.

/** What an authenticator app shows for `secret` (RFC 6238), `ahead` steps of 30 seconds from now. */
function totp(secret:string,ahead=0):string {
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits='';
  for(const ch of secret.replace(/\s+/g,'').toUpperCase()) bits+=alphabet.indexOf(ch).toString(2).padStart(5,'0');
  const key=Buffer.from(bits.match(/.{8}/g)!.map((b)=>parseInt(b,2)));
  const step=Buffer.alloc(8);
  step.writeBigUInt64BE(BigInt(Math.floor(Date.now()/1000/30)+ahead));
  const mac=createHmac('sha1',key).update(step).digest();
  const o=mac[mac.length-1]&15;
  return String((mac.readUInt32BE(o)&0x7fffffff)%1_000_000).padStart(6,'0');
}

const fixture={
  settings:{company_name:'Two-step Pumps',planning_start:'2026-01-05',horizon_days:28,default_calendar:'CAL',wacc:0,holding_spread:0},
  calendars:[{id:'CAL',workdays:[0,1,2,3,4,5,6]}],
  locations:[{id:'P',type:'plant'},{id:'S',type:'supplier'}],
  products:[{id:'A',type:'FG',price:25}],
  location_products:[{location:'P',product:'A',on_hand:10,lot_sizing:{policy:'L4L'}}],
  purchasing_sources:[{id:'BUY-A',supplier:'S',location:'P',product:'A',price:10,lead_time_days:1}],
  demand:[{id:'F1',location:'P',product:'A',date:'2026-01-12',qty:100,kind:'forecast'}],
};
const PASSWORD='two-step-pumps-20261015';

async function imported(page:Page) {
  const chooser=page.waitForEvent('filechooser');
  if(await page.getByRole('button',{name:'Import a file',exact:true}).count()) {
    await page.getByRole('button',{name:'Import a file',exact:true}).click();
  } else {
    await page.getByRole('button',{name:'More',exact:true}).click();
    await page.getByRole('menuitem',{name:'Import a dataset file…'}).click();
  }
  await (await chooser).setFiles({name:'pumps.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
  await expect(page.locator('.topbar .company')).toHaveText('Two-step Pumps');
}

test('two-step sign-in: turn it on, sign in with the code, require it of the company',async({page})=>{
  await page.goto('/'); await imported(page); await page.goto('/#/account');
  await page.getByRole('tab',{name:'Make an account'}).click();
  const email=`two-step-${Date.now()}@example.invalid`;
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Your name').fill('Two-step owner');
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.getByRole('button',{name:'Make the account',exact:true}).click();
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);

  // an owner cannot require it before having it
  const required=page.getByRole('checkbox',{name:/Every member signs in with two steps/});
  await required.click();      // refused: the box is unticked again and says why
  await expect(page.getByText(/turn on two-step sign-in for your own account first/)).toBeVisible();
  await expect(required).not.toBeChecked();

  // turn it on: the password again, the key for the app, a code back, the recovery codes once
  await page.getByLabel('Your password').fill(PASSWORD);
  await page.getByRole('button',{name:'Turn on two-step sign-in',exact:true}).click();
  const key=(await page.getByLabel('Key for the app').textContent())!.trim();
  expect(key.replace(/ /g,'')).toMatch(/^[A-Z2-7]{32}$/);
  await page.getByLabel('Code from your app').fill('000000');
  await page.getByRole('button',{name:'Turn it on',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('that code is not right');
  await page.getByLabel('Code from your app').fill(totp(key));
  await page.getByRole('button',{name:'Turn it on',exact:true}).click();
  const codes=page.getByRole('list',{name:'Recovery codes'}).locator('code');
  await expect(codes).toHaveCount(10);
  const recovery=(await codes.first().textContent())!;
  await page.getByRole('button',{name:'I have kept them',exact:true}).click();
  await expect(page.getByText('two-step sign-in on')).toBeVisible();
  await expect(page.getByText('10 recovery codes left')).toBeVisible();

  // now the company can require it; the history says so
  await required.check();
  await expect(required).toBeChecked();
  await page.goto('/#/history');
  await expect(page.getByText('two-step sign-in is required of every member').first()).toBeVisible();

  // sign out, and in again: the password alone is not enough
  await page.goto('/#/account');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByText('The password is right.')).toBeVisible();
  await page.getByLabel('Code from the app').fill(totp(key,1));
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('button',{name:'Open Two-step Pumps',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Open Two-step Pumps',exact:true}).click();
  await expect(page.locator('.topbar .company')).toHaveText('Two-step Pumps');

  // once more with a recovery code instead of the app (a lost phone)
  await page.goto('/#/account');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByLabel('Code from the app').fill(recovery);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByText('9 recovery codes left')).toBeVisible();

  // a phone-width screen keeps the panel inside the page
  await page.setViewportSize({width:390,height:844});
  const wide=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
  expect(wide).toBe(false);
});

// ENTERPRISE_PLAN 1.4: download everything the account holds, then delete it, after being told what happens
test('the account downloads everything it holds, then deletes itself and its company',async({page})=>{
  await page.goto('/'); await imported(page); await page.goto('/#/account');
  await page.getByRole('tab',{name:'Make an account'}).click();
  const email=`leaving-${Date.now()}@example.invalid`;
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Your name').fill('Leaving owner');
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.getByRole('button',{name:'Make the account',exact:true}).click();
  await page.getByRole('button',{name:'Keep it on the server',exact:true}).click();
  await expect(page.locator('.save-chip .save-long')).toHaveText(/^Saved/);

  await page.getByRole('button',{name:'Download everything',exact:true}).click();
  await page.getByRole('form',{name:'Download everything'}).getByLabel('Your password').fill(PASSWORD);
  const download=page.waitForEvent('download');
  await page.getByRole('button',{name:'Download',exact:true}).click();
  const file=await download;
  expect(file.suggestedFilename()).toMatch(/^scp-account-\d{4}-\d{2}-\d{2}\.json$/);
  const data=JSON.parse(readFileSync(await file.path(),'utf8'));
  expect(data.account.email).toBe(email);
  expect(data.companies.map((c:{name:string})=>c.name)).toEqual(['Two-step Pumps']);
  expect(data.companies[0].dataset.products[0].id).toBe('A');

  await page.getByRole('button',{name:'Delete my account…',exact:true}).click();
  const form=page.getByRole('form',{name:'Delete my account'});
  await expect(form.getByText('You are the only owner of these.')).toBeVisible();
  await expect(form.getByLabel('What happens to Two-step Pumps')).toHaveValue('delete');   // nobody to hand it to
  await form.getByLabel('Your password').fill(PASSWORD);
  const button=form.getByRole('button',{name:'Delete my account',exact:true});
  await expect(button).toBeDisabled();
  await form.getByLabel('Type DELETE to confirm').fill('delete');
  page.once('dialog',(d)=>{ expect(d.message()).toContain('Two-step Pumps deleted'); void d.accept(); });
  await button.click();
  await expect(page.getByRole('tab',{name:'Sign in'})).toBeVisible();
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel(/^Password/).fill(PASSWORD);
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('not right');
});
