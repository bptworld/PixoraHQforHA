import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE||new URL('../haflow/package.json',import.meta.url));
const {chromium}=require('playwright');
const html=readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url),'utf8');
const catalog=JSON.parse(readFileSync(new URL('../pixora_led_displays/card_catalog.json',import.meta.url),'utf8'));
const card={installed:true,...catalog.cards.find(c=>c.id==='college_football'),specialTests:{scoreAnimationTarget:{label:'Score Animation'}}};
const state={cards:[card],decks:{},devices:{},groups:{wall:{name:'3way',members:['left']},second:{name:'Desk pair',members:['left']}},graphics:{},settings:{},runtime:{},displays:[{id:'left',name:'Left-64',width:64,height:32,version:'2.0.19'}]};
let requests=0,prepares=0,fail=false,release;
const browser=await chromium.launch();
try{
 const page=await browser.newPage({viewport:{width:768,height:1024}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio')return route.fulfill({json:state});
  if(path==='/api/displays/left/status')return route.fulfill({json:{display:state.displays[0]}});
  if(path==='/api/automation-status')return route.fulfill({json:{restart_required:false}});
  if(path==='/api/studio/prepare-graphic'){prepares++;return route.fulfill({json:{prepared:true}})}
  if(path==='/api/studio/test-graphic'){
   requests++;const payload=route.request().postDataJSON();
   assert.equal(payload.display,'left');assert.equal(payload.card,'college_football');assert.equal(payload.option,'scoreAnimationTarget');
   assert.equal(payload.options.favoriteTeam,'ALA');assert.equal(payload.options.scoreAnimationTarget,'group:second');
   await new Promise(resolve=>release=resolve);
   return fail?route.fulfill({status:400,json:{error:'Display is unavailable. Nothing was sent.'}}):route.fulfill({json:{queued:true,render_ms:120,message:'Test graphic queued. The deck continues with the next card after the interrupt.'}});
  }
  if(new URL(route.request().url()).hostname==='raw.githubusercontent.com')return route.abort();
  throw Error('Unexpected request '+path);
 });
 await page.goto('http://studio.test/');
 await page.getByRole('button',{name:'Options & add to deck',exact:true}).click();
 await page.getByLabel('Team',{exact:true}).selectOption('ALA');
 await page.getByLabel('Score Animation',{exact:true}).selectOption({label:'Desk pair'});
 assert.equal(await page.getByRole('option',{name:'Group Wall',exact:true}).count(),0);
 assert.equal(await page.getByLabel('Score Animation',{exact:true}).getByRole('option',{name:'3way',exact:true}).count(),1);
 await page.locator('#optionsDialog').screenshot({path:'D:/planner/.build-tmp/led-graphic-group-name.png'});
 await page.waitForResponse(r=>r.url().endsWith('/api/studio/prepare-graphic'));
 assert.ok(prepares>0);assert.equal(requests,0,'Preparation sent a Test');
 const test=page.getByRole('button',{name:'Test Score Animation',exact:true});
 await test.click();await page.waitForFunction(()=>document.querySelector('#optionsFeedback').textContent.includes('Rendering test'));
 assert.equal(await test.isDisabled(),true);release();
 await page.locator('#optionsFeedback').filter({hasText:'Rendered in 0.12s'}).waitFor();
 assert.equal(await page.locator('#optionsDialog').isVisible(),true);assert.equal(await page.getByLabel('Team',{exact:true}).inputValue(),'ALA');
 fail=true;await test.click();await page.waitForFunction(()=>document.querySelector('#optionsFeedback').textContent.includes('Rendering test'));release();
 await page.locator('#optionsFeedback').filter({hasText:'Display is unavailable'}).waitFor();
 assert.equal(await page.getByLabel('Team',{exact:true}).inputValue(),'ALA');assert.equal(requests,2);
 assert.equal(await page.locator('#optionsDialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);
 state.groups.wall.name='Main wall';await page.reload();await page.getByRole('button',{name:'Options & add to deck',exact:true}).click();
 assert.equal(await page.getByLabel('Score Animation',{exact:true}).getByRole('option',{name:'Main wall',exact:true}).count(),1);
 state.groups={};await page.reload();await page.getByRole('button',{name:'Options & add to deck',exact:true}).click();
 assert.equal(await page.getByLabel('Score Animation',{exact:true}).getByRole('option',{name:'No group assigned',exact:true}).evaluate(e=>e.disabled),true);
 assert.deepEqual(errors,[]);
 console.log('Graphic Test browser passed: adjacent accessible button, current options, busy feedback, success/error, no implicit save, retained fields and tablet layout.');
}finally{await browser.close()}
