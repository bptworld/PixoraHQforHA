import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('D:/planner/connect-features/cloud/render/planner/package.json');
const {chromium}=require('playwright');
const html=readFileSync(new URL('../pixora_led_displays/display_setup.html',import.meta.url),'utf8');
const browser=await chromium.launch();
try{
 const page=await browser.newPage({viewport:{width:1100,height:1000},acceptDownloads:true});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let profiles=[],jobs={},images=0,flashes=0;
 await page.route('**/*',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/new-display')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/setup'&&route.request().method()==='GET')return route.fulfill({json:{profiles,jobs,ports:[{port:'/dev/ttyACM0',label:'MatrixPortal S3'}]}});
  if(path==='/api/setup'&&route.request().method()==='POST'){
   const data=route.request().postDataJSON();assert.equal(data.name,'Living room');assert.equal(data.password,'test-password');assert.equal(data.width,128);
   profiles=[{id:'abc',name:data.name,ssid:data.ssid,width:data.width,hasPassword:true}];return route.fulfill({json:{id:'abc',profiles}});
  }
  if(path==='/api/setup/abc/image'){images++;return route.fulfill({contentType:'application/octet-stream',headers:{'Content-Disposition':'attachment; filename="pixora-first-install.bin"'},body:Buffer.from('test firmware')})}
  if(path==='/api/setup/abc/flash'){flashes++;assert.equal(route.request().postDataJSON().confirmErase,true);jobs.abc={stage:'Firmware verified. Finish connecting below.',running:false,verified:true,host:'192.168.1.50'};return route.fulfill({json:{started:true}})}
  if(path==='/api/setup/abc/finish'){assert.equal(route.request().postDataJSON().host,'192.168.1.50');return route.fulfill({json:{displays:[]}})}
  throw Error('Unexpected request '+path);
 });
 await page.goto('http://studio.test/new-display');await page.getByLabel('Display name',{exact:true}).fill('Living room');await page.getByLabel('Panels',{exact:true}).selectOption('128');await page.getByLabel('Wi-Fi name (2.4 GHz)',{exact:true}).fill('Home network');await page.getByLabel('Wi-Fi password',{exact:true}).fill('test-password');await page.getByRole('button',{name:'Save & continue'}).click();
 await page.getByRole('heading',{name:'How do you want to install it?'}).waitFor();assert.equal(await page.getByLabel('Wi-Fi password',{exact:true}).inputValue(),'');
 await page.locator('[data-method="later"]').click();assert.equal(await page.locator('#install').isVisible(),false);
 await page.locator('[data-method="computer"]').click();assert.match(await page.locator('#computerMethod').innerText(),/local HTTP/);
 await page.locator('#install').click();assert.equal(images,0);await page.getByText('Confirm the first-install checkbox before continuing.',{exact:true}).waitFor();
 await page.locator('#erase').check();const downloaded=page.waitForEvent('download');await page.locator('#install').click();assert.equal((await downloaded).suggestedFilename(),'pixora-first-install.bin');assert.equal(images,1);assert.equal(flashes,0);
 await page.locator('[data-method="ha"]').click();await page.locator('#install').click();await page.locator('#setupHost').waitFor();await page.waitForFunction(()=>document.getElementById('setupHost').value==='192.168.1.50');assert.equal(flashes,1);
 await page.getByRole('button',{name:'Connect this display'}).click();await page.getByText('Connected! Open LED Studio to assign a deck.',{exact:true}).waitFor();
 await page.screenshot({path:'D:/planner/.build-tmp/led-new-display-desktop.png',fullPage:true});await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:'D:/planner/.build-tmp/led-new-display-mobile.png',fullPage:true});assert.deepEqual(errors,[]);
 console.log('New display browser passed: saved profile, cleared password, four install choices, local HTTP fallback download, erase guard, one USB job, detected IP, connection finish and mobile layout.');
}finally{await browser.close()}
