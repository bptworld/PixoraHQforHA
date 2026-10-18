import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('D:/planner/connect-features/cloud/render/planner/package.json');
const {chromium}=require('playwright');
const html=readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url),'utf8');
const state={cards:[],decks:{},devices:{},groups:{},graphics:{},settings:{},runtime:{},displays:[]};
const browser=await chromium.launch();
try{
 const page=await browser.newPage();let reads=0,writes=0,available=false,setupAvailable=false;
 const ingress='/api/hassio_ingress/test/';
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const rawPath=new URL(route.request().url()).pathname;
  if(rawPath==='/app/pixora_led_displays')return route.fulfill({contentType:'text/html',body:`<iframe title="Pixora LED Studio" src="${ingress}"></iframe>`});
  const path=rawPath.startsWith(ingress)?'/'+rawPath.slice(ingress.length):rawPath;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio'){
   reads++;
   if(!available)return route.abort('failed');
   return route.fulfill({json:state});
  }
  if(path==='/api/automation-status')return setupAvailable?route.fulfill({json:{}}):route.fulfill({status:503,contentType:'text/html',body:'Restarting'});
  if(route.request().method()==='POST'){writes++;return route.abort('failed')}
  return route.fulfill({json:{}});
 });
 await page.goto('http://homeassistant.test/app/pixora_led_displays');
 const ui=page.frameLocator('iframe');
 await ui.getByRole('status').filter({hasText:'No cloud account is needed'}).waitFor();
 assert.equal(reads,1,'The failed read is not immediately repeated');
 available=true;
 await ui.getByRole('status').filter({hasText:'Connected to local LED Studio.'}).waitFor();
 await ui.getByRole('button',{name:'My Apps',exact:true}).click();
 await ui.getByText('No custom apps imported yet.',{exact:false}).waitFor();
 assert.ok(reads>=2,'Initial loading recovered without a page reload');
 await ui.locator('#haSetupText').filter({hasText:'Could not check HA setup yet'}).waitFor();
 assert.equal(await ui.getByRole('heading',{name:'My Apps',exact:true}).isVisible(),true,'Setup check failure must not block Studio');
 setupAvailable=true;
 // A write failure must never be automatically replayed.
 await ui.getByRole('button',{name:'Setup Options',exact:true}).click();
 await ui.getByLabel('Time zone',{exact:true}).fill('UTC');
 await ui.getByRole('button',{name:'Save defaults',exact:true}).click();
 await ui.getByRole('alert').filter({hasText:'It was not retried'}).waitFor();
 assert.equal(writes,1);
 // A rejected HA ingress session needs a fresh session, not repeated auth requests.
 const authPage=await browser.newPage();let authReads=0;
 await authPage.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  authReads++;return route.fulfill({status:403,contentType:'text/html',body:'Forbidden'});
 });
 await authPage.goto('http://studio.test/');
 await authPage.getByRole('alert').filter({hasText:'Reopen LED Studio'}).waitFor();
 assert.equal(authReads,1,'Do not retry rejected ingress sessions');
 await authPage.close();
 // A read that never answers times out, then the startup poll recovers.
 const timeoutPage=await browser.newPage();let timeoutReads=0;
 await timeoutPage.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio'){timeoutReads++;return timeoutReads===1?new Promise(()=>{}):route.fulfill({json:state})}
  return route.fulfill({json:{}});
 });
 await timeoutPage.goto('http://studio.test/');
 await timeoutPage.getByRole('status').filter({hasText:'Retrying automatically'}).waitFor({timeout:14000});
 await timeoutPage.getByRole('status').filter({hasText:'Connected to local LED Studio.'}).waitFor({timeout:12000});
 assert.equal(timeoutReads,2);await timeoutPage.close();
 // A stalled optional setup check must not keep Studio controls disabled.
 const slowPage=await browser.newPage();
 await slowPage.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio')return route.fulfill({json:state});
  if(path==='/api/automation-status')return new Promise(()=>{});
  return route.fulfill({json:{}});
 });
 await slowPage.goto('http://studio.test/');
 await slowPage.getByRole('button',{name:'My Apps',exact:true}).click({timeout:2000});
 await slowPage.getByRole('heading',{name:'My Apps',exact:true}).waitFor();
 await slowPage.locator('#haSetupText').filter({hasText:'Could not check HA setup yet'}).waitFor({timeout:14000});
 assert.equal(await slowPage.getByRole('button',{name:'Decks',exact:true}).isEnabled(),true);
 await slowPage.close();
 // Persisted metadata accepted by 1.2.26 must remain editable without DOM errors.
 const legacyPage=await browser.newPage();
 const legacyCard={id:'custom_legacy',name:'Legacy card',detail:'Persisted app',custom:true,category:'My Apps',options:[
  {key:'message',label:'Message',type:'text',maxlength:-1},
  {key:'value',label:'Legacy number',type:'number',min:10,max:1,step:0,default:2}
 ]};
 await legacyPage.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio')return route.fulfill({json:{...state,cards:[legacyCard]}});
  return route.fulfill({json:{}});
 });
 await legacyPage.goto('http://studio.test/');
 await legacyPage.getByRole('button',{name:'Options & add to deck',exact:true}).click();
 await legacyPage.getByRole('dialog').waitFor();
 const legacyOptions=legacyPage.getByRole('dialog');
 assert.equal(await legacyOptions.getByLabel('Message',{exact:true}).getAttribute('maxlength'),null);
 assert.equal(await legacyOptions.getByLabel('Legacy number',{exact:true}).getAttribute('step'),'any');
 assert.equal(await legacyOptions.getByLabel('Legacy number',{exact:true}).getAttribute('min'),null);
 await legacyPage.close();
 assert.deepEqual(errors,[]);
 await page.screenshot({path:'D:/planner/.build-tmp/led-reload-recovery.png'});
 console.log('Reload recovery passed: local HTTP ingress iframe, failed/timed-out startup recovery, slow setup isolation, expired ingress and no write retries.');
}finally{await browser.close()}
