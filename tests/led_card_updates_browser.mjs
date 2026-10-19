import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire('D:/planner/connect-features/cloud/render/planner/package.json');
const {chromium}=require('playwright');
const html=readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url),'utf8');
const card={id:'clock',name:'Clock',category:'Utility',detail:'Local clock',options:[],installed:true};
let state={cards:[card],decks:{saved:{name:'Saved deck',items:[{id:'one',card:'clock',duration:10,enabled:true,options:{}}]}},devices:{panel:{deck:'saved',playing:true}},displays:[{id:'panel',name:'Kitchen',width:64,height:32,version:'2.0.27'}],runtime:{panel:{playing:true,status:'Clock'}},settings:{},groups:{},graphics:{},cardLibraryRevision:'aaaaaaaa'};
let attempts=0,release;
const browser=await chromium.launch();
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];
 await page.addInitScript(()=>localStorage.setItem('pixora-led-show-preview','false'));
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',async route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio')return route.fulfill({json:state});
  if(path==='/api/displays/panel/status')return route.fulfill({json:{display:state.displays[0]}});
  if(path==='/api/automation-status')return route.fulfill({json:{}});
  if(path==='/api/studio/preview')return route.fulfill({status:400,json:{error:'No preview in this update-control test'}});
  if(path==='/api/studio/update-cards'){
   assert.equal(route.request().method(),'POST');attempts++;
   if(attempts===1){await new Promise(resolve=>release=resolve);return route.fulfill({status:400,json:{error:'Card download failed. Your current cards are unchanged.'}})}
   state={...state,cardLibraryRevision:'bbbbbbbb',cards:[{...card,version:'2.0',options:[{key:'style',label:'New style',type:'select',default:'new',choices:['new','old']}]}]};
   return route.fulfill({json:{state,message:'Card library updated. Saved decks and playback settings preserved.'}});
  }
  throw Error('Unexpected browser request '+path);
 });
 await page.goto('http://studio.test/');await page.getByText('Library aaaaaaaa',{exact:true}).waitFor();
 const update=page.getByRole('button',{name:'Update cards',exact:true});await update.click();
 while(!release)await page.waitForTimeout(10);
 assert.equal(await page.getByRole('button',{name:'Working…',exact:true}).isDisabled(),true);
 release();await page.locator('#notice').filter({hasText:'Card download failed'}).waitFor();
 assert.equal(await update.isEnabled(),true);assert.equal(attempts,1);
 await update.click();await page.getByText('Library bbbbbbbb',{exact:true}).waitFor();
 assert.equal(attempts,2);assert.equal(state.devices.panel.playing,true);
 await page.getByRole('button',{name:'Options & add to deck',exact:true}).click();
 assert.equal(await page.getByLabel('New style',{exact:true}).inputValue(),'new');
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 await page.screenshot({path:'D:/planner/.build-tmp/led-card-updates-desktop.png'});
 await page.setViewportSize({width:768,height:1024});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.deepEqual(errors,[]);
 console.log('Card update browser passed: local loading, busy feedback, failed-update recovery without retries, updated revision/options, saved playing deck and tablet layout.');
}finally{await browser.close()}
