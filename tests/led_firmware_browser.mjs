import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE||new URL('../haflow/package.json',import.meta.url));
const {chromium}=require('playwright');
const browser=await chromium.launch();
try{
 const page=await browser.newPage();let updates=0,fail=false;
 await page.route('http://led.test/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:readFileSync(new URL('../pixora_led_displays/index.html',import.meta.url),'utf8')});
  if(url.pathname==='/api/displays')return route.fulfill({json:{displays:[{id:'left',name:'Left',width:64,height:32}]}});
  if(url.pathname==='/api/automation-status')return route.fulfill({json:{restart_required:true,can_restart:false,error:'Home Assistant API access is unavailable.'}});
  if(url.pathname==='/api/firmware')return route.fulfill({json:{current:'2.0.14',latest:'2.0.18',available:true,preview:true}});
  if(url.pathname==='/api/firmware/update'){
   updates++;assert.equal(url.searchParams.get('id'),'left');assert.deepEqual(route.request().postDataJSON(),{version:'2.0.18'});
   return fail?route.fulfill({status:400,json:{error:'Update outcome is uncertain.'}}):route.fulfill({json:{updated:true,verified:true,current:'2.0.18',message:'Firmware 2.0.18 confirmed running. Display reconnected and ready.'}});
  }
  throw Error('Unexpected request '+url.pathname);
 });
 await page.goto('http://led.test/');
 await page.locator('#autoUpdate').waitFor({state:'visible'});await page.waitForFunction(()=>!document.getElementById('autoUpdate').disabled);
 assert.equal(await page.locator('#restartHA').isVisible(),false);
 assert.match(await page.locator('#firmwareInfo').innerText(),/2.0.18 \(preview\)/);
 await page.locator('#autoUpdate').click();await page.locator('#firmwareStatus').filter({hasText:'confirmed'}).waitFor();
 assert.equal(await page.locator('#firmwareInfo').innerText(),'Installed: 2.0.18. Up to date.');
 assert.equal(updates,1);assert.equal(await page.locator('#autoUpdate').isVisible(),false);
 await page.locator('#checkFirmware').click();await page.locator('#autoUpdate').waitFor({state:'visible'});fail=true;
 await page.locator('#autoUpdate').click();await page.locator('#firmwareStatus.error').waitFor();
 assert.equal(updates,2);assert.match(await page.locator('#firmwareStatus').innerText(),/not retried/);
 assert.equal(await page.locator('#autoUpdate').isVisible(),false);
 console.log('Firmware browser passed: automatic check, preview label, one-click selected-panel update, no file upload and no automatic retry.');
}finally{await browser.close()}
