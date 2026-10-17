// Set PLAYWRIGHT_PACKAGE to a package.json with Playwright installed if needed.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require = createRequire(process.env.PLAYWRIGHT_PACKAGE || new URL('../haflow/package.json', import.meta.url));
const {chromium} = require('playwright');
const html = readFileSync(new URL('../pixora_led_displays/index.html', import.meta.url), 'utf8');
const browser = await chromium.launch();
try {
 const page = await browser.newPage({viewport:{width:800,height:600}});
 let mode='success', calls=0, release, sent;
 const old={id:'old',name:'Existing display',width:64,height:32};
 const added={id:'new',name:'Left-64',width:64,height:32};
 await page.route('http://led.test/**', async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
  if(url.pathname==='/api/automation-status')return route.fulfill({json:{restart_required:true,error:''}});
  if(url.pathname==='/api/displays'){
   if(route.request().method()==='GET')return route.fulfill({json:{displays:[old]}});
   calls++;
   assert.deepEqual(route.request().postDataJSON(),{name:'Left-64',host:'192.168.4.90'});
   if(mode==='waiting')await new Promise(resolve=>{release=resolve});
   return mode==='failure'?route.fulfill({status:400,json:{error:'Pairing window closed. Restart the panel.'}}):route.fulfill({json:{displays:[old,added]}});
  }
  if(url.pathname==='/api/show'){sent=route.request().postDataJSON();return route.fulfill({json:{accepted:true}})}
  throw Error('Unexpected request: '+url.pathname);
 });
 await page.goto('http://led.test/');
 await page.waitForFunction(()=>!document.getElementById('pair').disabled);
 const name=page.getByLabel('Name',{exact:true}),host=page.getByLabel('Display IP address',{exact:true}),button=page.getByRole('button',{name:'Connect display',exact:true});
 await name.fill('Left-64');await host.fill('192.168.4.90');mode='waiting';await button.click();
 await page.locator('#pairStatus.pending').waitFor();assert.equal(await name.isDisabled(),true);assert.equal(await host.isDisabled(),true);assert.equal(calls,1);
 release();await page.locator('#pairStatus.success').waitFor();
 assert.equal(await name.inputValue(),'');assert.equal(await host.inputValue(),'');assert.equal(await page.locator('#display').inputValue(),'new');
 const box=await page.locator('#pairStatus').boundingBox();assert.ok(box.y>=0&&box.y+box.height<=600,'Confirmation should be visible near the clicked button');
 await page.getByRole('button',{name:'Show card',exact:true}).click();await page.locator('#sendStatus').filter({hasText:'Card accepted'}).waitFor();assert.equal(sent.id,'new');
 await name.fill('Left-64');await host.fill('192.168.4.90');mode='failure';await button.click();
 await page.locator('#pairStatus[role=alert]').waitFor();assert.match(await page.locator('#pairStatus').innerText(),/Pairing window closed/);
 assert.equal(await name.inputValue(),'Left-64');assert.equal(await host.inputValue(),'192.168.4.90');assert.equal(await button.isEnabled(),true);assert.equal(calls,2);
 console.log('LED pairing browser checks passed: inline progress/success/error, visible confirmation, clear on success, retain on failure, duplicate prevention and correct selected display.');
} finally {await browser.close()}
