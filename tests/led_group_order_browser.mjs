import assert from 'node:assert/strict';
import {readFileSync,mkdirSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE||new URL('../haflow/package.json',import.meta.url));
const {chromium}=require('playwright');
let state={cards:[],decks:{},devices:{},groups:{},graphics:{},settings:{},runtime:{},displays:[
 {id:'center',name:'Center-128',width:128,height:32,version:'2.0.27'},
 {id:'left',name:'Left-64',width:64,height:32,version:'2.0.27'},
 {id:'right',name:'Right-64',width:64,height:32,version:'2.0.27'}]};
let fail=false,lastSaved;
const browser=await chromium.launch();
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.route('http://groups.test/**',route=>{
  const path=new URL(route.request().url()).pathname;
  if(path==='/')return route.fulfill({contentType:'text/html',body:readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url),'utf8')});
  if(path==='/api/studio')return route.fulfill({json:state});
  if(path==='/api/automation-status')return route.fulfill({json:{restart_required:false}});
  if(path.startsWith('/api/displays/'))return route.fulfill({json:{display:state.displays.find(d=>path.includes('/'+d.id+'/'))}});
  if(path==='/api/studio/groups'){
   const payload=route.request().postDataJSON();
   if(fail)return route.fulfill({status:503,json:{error:'Could not save group'}});
   lastSaved=payload;state.groups[payload.id||'group1']={name:payload.name,members:payload.members};
   return route.fulfill({json:state});
  }
  throw Error('Unexpected request '+path);
 });
 await page.goto('http://groups.test/');
 await page.getByRole('button',{name:'Device Groups',exact:true}).click();
 await page.getByLabel('Group name',{exact:true}).fill('3way');
 for(const name of ['Center-128','Left-64','Right-64'])await page.getByRole('checkbox',{name,exact:true}).check();
 const draft=page.getByLabel('New group display order',{exact:true});
 assert.deepEqual(await draft.locator('strong').allTextContents(),['Center-128','Left-64','Right-64']);
 await draft.getByRole('button',{name:'Move left: Left-64',exact:true}).click();
 assert.deepEqual(await draft.locator('strong').allTextContents(),['Left-64','Center-128','Right-64']);
 assert.match(await draft.innerText(),/Position 1.*Left edge/);
 assert.match(await draft.innerText(),/Position 3.*Right edge/);
 assert.equal(await draft.getByRole('button',{name:'Move left: Left-64',exact:true}).isDisabled(),true);
 await page.getByRole('button',{name:'Save group',exact:true}).click();
 await page.locator('#notice').filter({hasText:'Display group saved'}).waitFor();
 assert.deepEqual(lastSaved.members,['left','center','right']);
 const saved=page.getByLabel('3way display order',{exact:true});
 assert.deepEqual(await saved.locator('strong').allTextContents(),['Left-64','Center-128','Right-64']);
 await saved.getByRole('button',{name:'Move right: Left-64',exact:true}).click();
 await page.locator('#notice').filter({hasText:'Group display order saved'}).waitFor();
 assert.deepEqual(lastSaved.members,['center','left','right']);
 await page.reload();await page.getByRole('button',{name:'Device Groups',exact:true}).click();
 assert.deepEqual(await saved.locator('strong').allTextContents(),['Center-128','Left-64','Right-64']);
 await page.getByLabel('Group name',{exact:true}).fill('Keep my edits');
 await page.getByRole('checkbox',{name:'Left-64',exact:true}).check();fail=true;
 await page.getByRole('button',{name:'Save group',exact:true}).click();
 await page.locator('#notice').filter({hasText:'Could not save group'}).waitFor();
 assert.equal(await page.getByLabel('Group name',{exact:true}).inputValue(),'Keep my edits');
 assert.equal(await page.getByRole('checkbox',{name:'Left-64',exact:true}).isChecked(),true);
 fail=false;await saved.getByRole('button',{name:'Move left: Left-64',exact:true}).click();await page.locator('#notice').filter({hasText:'Group display order saved'}).waitFor();
 await page.reload();await page.getByRole('button',{name:'Device Groups',exact:true}).click();
 await page.getByLabel('Group name',{exact:true}).fill('New wall');
 for(const name of ['Left-64','Center-128','Right-64'])await page.getByRole('checkbox',{name,exact:true}).check();
 mkdirSync('D:/planner/.build-tmp',{recursive:true});
 await page.locator('#groupsTab').screenshot({path:'D:/planner/.build-tmp/led-group-order.png'});
 for(const width of [768,375]){
  await page.setViewportSize({width,height:1000});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Group order overflows at '+width);
 }
 console.log('Group order passed: numbered positions, draft rearrangement, saved rearrangement, persisted order, retained failure edits and tablet/mobile layout.');
}finally{await browser.close()}
