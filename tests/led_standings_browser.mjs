import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const {chromium}=createRequire(process.env.PLAYWRIGHT_PACKAGE||'D:/planner/connect-features/cloud/render/planner/package.json')('playwright');
const html=readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url),'utf8');
const card={installed:true,id:'nfl_standings',name:'NFL Standings',category:'Sports',standingsBrowser:'public',options:[{key:'group',label:'Conference / division',type:'select',default:'afc',choices:[{value:'afc',label:'AFC'},{value:'nfc',label:'NFC'}]}]};
const state={cards:[card],decks:{deck:{name:'Standings',items:[{id:'item',card:card.id,options:{group:'espn:4'},duration:10,enabled:true}]}},devices:{left:{deck:'deck',playing:false}},runtime:{},groups:{},graphics:{},settings:{},displays:[{id:'left',name:'Left-64',width:64,height:32,version:'2.0.27'}]};
const browser=await chromium.launch();let saved,fail=false;
try{
 const page=await browser.newPage({viewport:{width:768,height:1024}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:html});
  if(path==='/api/studio')return route.fulfill({json:state});
  if(path==='/api/automation-status')return route.fulfill({json:{restart_required:false}});
  if(path==='/api/displays/left/status')return route.fulfill({json:{display:state.displays[0]}});
  if(path==='/api/studio/preview')return route.fulfill({status:204});
  if(path==='/api/studio/standings-groups'){
   if(fail)return route.fulfill({status:400,json:{error:'Provider unavailable. Try loading divisions again.'}});
   const payload=route.request().postDataJSON();
   if(!payload.group)return route.fulfill({json:{groups:[{value:'espn:8',label:'AFC'},{value:'espn:7',label:'NFC'}]}});
   if(['espn:8','afc'].includes(payload.group))return route.fulfill({json:{selection:{value:'espn:8',label:'AFC'},groups:[{value:'espn:4',label:'AFC East'},{value:'espn:12',label:'AFC North'}]}});
   return route.fulfill({json:{selection:{value:payload.group,label:payload.group==='espn:4'?'AFC East':'AFC North'},groups:[],message:'No further divisions are available from this provider.'}});
  }
  if(path==='/api/studio/decks'){
   saved=route.request().postDataJSON();state.decks.deck={name:saved.name,items:saved.items};return route.fulfill({json:{id:'deck',state}});
  }
  return route.abort();
 });
 await page.goto('http://studio.test/');await page.getByRole('button',{name:'Decks',exact:true}).click();
 await page.locator('#deckItems').getByRole('button',{name:'Options',exact:true}).click();
 const group=page.getByLabel('Conference / division',{exact:true});
 await group.getByRole('option',{name:'AFC East',exact:true}).waitFor({state:'attached'});assert.equal(await group.inputValue(),'espn:4','Reopening lost the saved provider ID');
 await group.selectOption('espn:8');const divisions=page.getByLabel('Drill down to division',{exact:true});await divisions.waitFor();
 await divisions.selectOption('espn:12');await group.getByRole('option',{name:'AFC North',exact:true}).waitFor({state:'attached'});assert.equal(await group.inputValue(),'espn:12');
 await page.locator('#optionsDialog').screenshot({path:'D:/planner/.build-tmp/led-standings-divisions.png'});
 await page.getByRole('button',{name:'Save in deck & download',exact:true}).click();await page.locator('#optionsDialog').waitFor({state:'hidden'});
 assert.equal(saved.items[0].options.group,'espn:12');assert.equal('' in saved.items[0].options,false,'Unnamed drill-down control leaked into saved options');
 await page.locator('#deckItems').getByRole('button',{name:'Options',exact:true}).click();await group.getByRole('option',{name:'AFC North',exact:true}).waitFor({state:'attached'});assert.equal(await group.inputValue(),'espn:12');
 fail=true;await page.getByRole('button',{name:'Load divisions',exact:true}).click();await page.getByText('Provider unavailable. Try loading divisions again.',{exact:true}).waitFor();assert.equal(await group.inputValue(),'espn:12','Provider error erased saved division');
 fail=false;state.decks.deck.items[0].options.group='afc';await page.reload();await page.getByRole('button',{name:'Decks',exact:true}).click();await page.locator('#deckItems').getByRole('button',{name:'Options',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[name=group]')?.value==='espn:8');await page.getByLabel('Drill down to division',{exact:true}).waitFor();
 assert.equal(await page.locator('#optionsDialog').evaluate(e=>e.scrollWidth<=e.clientWidth),true);assert.deepEqual(errors,[]);
 console.log('Standings browser passed: saved-ID restore, conference-to-division drill-down, exact save/reopen, retained selection on provider failure and tablet layout.');
}finally{await browser.close()}
