import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE||new URL('../haflow/package.json',import.meta.url));
const {chromium}=require('playwright');
const html=readFileSync(new URL('../pixora_led_displays/index.html',import.meta.url),'utf8');
const browser=await chromium.launch();
try{
 const page=await browser.newPage();
 let items=[{id:'left',name:'Left-64',width:64,height:32}],fail=false,deletes=0;
 await page.route('http://led.test/**',async route=>{
  const url=new URL(route.request().url()),method=route.request().method();
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:html});
  if(url.pathname==='/api/automation-status')return route.fulfill({json:{restart_required:true,error:''}});
  if(url.pathname==='/api/firmware')return route.fulfill({json:{current:'2.0.18',latest:'2.0.18',available:false,preview:true}});
  if(url.pathname==='/api/displays')return route.fulfill({json:{displays:items}});
  if(url.pathname==='/api/displays/left/panel'){if(fail)return route.fulfill({status:400,json:{error:'Size change was not confirmed'}});items=[{...items[0],width:route.request().postDataJSON().width}];return route.fulfill({json:{verified:true,displays:items,message:'Panel confirmed as 128×32.'}})}
  assert.equal(url.pathname,'/api/displays/left');
  if(method==='DELETE')deletes++;
  if(fail)return route.fulfill({status:400,json:{error:'Storage unavailable'}});
  if(method==='PATCH')items=[{...items[0],name:route.request().postDataJSON().name}];
  if(method==='DELETE')items=[];
  return route.fulfill({json:{displays:items}});
 });
 await page.goto('http://led.test/');await page.waitForFunction(()=>!document.getElementById('pair').disabled);
 assert.equal(await page.getByRole('heading',{name:'Manage displays',exact:true}).isVisible(),true);assert.equal(await page.getByLabel('Panel size',{exact:true}).isVisible(),true);
 assert.equal(await page.getByRole('heading',{name:'Send a card',exact:true}).count(),0);
 const name=page.getByLabel('Display name',{exact:true});
 assert.equal(await name.inputValue(),'Left-64');
 await name.fill('Porch');fail=true;await page.getByRole('button',{name:'Save name',exact:true}).click();
 await page.locator('#manageStatus.error').waitFor();assert.equal(await name.inputValue(),'Porch');assert.match(await page.locator('#display').innerText(),/Left-64/);
 fail=false;await page.getByRole('button',{name:'Save name',exact:true}).click();await page.locator('#manageStatus.success').waitFor();
 assert.equal(await page.locator('#display').inputValue(),'left');assert.match(await page.locator('#display').innerText(),/Porch/);
 await page.getByLabel('Panel size',{exact:true}).selectOption('128');fail=true;await page.getByRole('button',{name:'Save panel size',exact:true}).click();await page.locator('#manageStatus.error').waitFor();assert.equal(await page.getByLabel('Panel size',{exact:true}).inputValue(),'128');fail=false;await page.getByRole('button',{name:'Save panel size',exact:true}).click();await page.locator('#manageStatus.success').filter({hasText:'128×32'}).waitFor();assert.match(await page.locator('#display').innerText(),/128×32/);
 await page.locator('#remove').click();assert.equal(await page.locator('#removeQuestion').innerText(),'Remove Porch?');
 await page.getByRole('button',{name:'Keep display',exact:true}).click();assert.equal(deletes,0);assert.equal(await page.locator('#removeConfirm').isVisible(),false);
 await page.locator('#remove').click();fail=true;await page.locator('#confirmRemove').click();await page.locator('#manageStatus.error').waitFor();assert.match(await page.locator('#display').innerText(),/Porch/);
 fail=false;await page.locator('#confirmRemove').click();await page.locator('#manageStatus.success').waitFor();
 assert.equal(await page.locator('#display').inputValue(),'');assert.match(await page.locator('#display').innerText(),/Add a display/);
 assert.equal(await page.locator('#rename').isDisabled(),true);assert.equal(await page.locator('#remove').isDisabled(),true);
 assert.equal(await page.locator('#removeConfirm').isVisible(),false);assert.equal(deletes,2);
 console.log('LED management browser checks passed: rename, retained edits on failure, confirmed/cancelled removal, failure recovery and empty list.');
}finally{await browser.close()}
