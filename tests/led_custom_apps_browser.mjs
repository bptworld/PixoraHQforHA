import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
const require = createRequire(process.env.PLAYWRIGHT_PACKAGE || 'D:/planner/connect-features/cloud/render/planner/package.json');
const { chromium } = require('playwright');
const html = readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url),'utf8');
const source = readFileSync(new URL('../pixora_led_displays/custom_card_starter.py',import.meta.url));
const card = {id:'custom_my_message',name:'My Message',detail:'A custom card',category:'My Apps',custom:true,version:'1.0.0',options:[{key:'message',label:'Message',type:'text',default:'Hello Pixora'},{key:'bright',label:'Bright text',type:'checkbox',default:true}]};
let imports = 0, deletes = 0;
const state = {cards:[],decks:{},devices:{},groups:{},graphics:{},settings:{},runtime:{},displays:[]};
const browser = await chromium.launch();
try {
 const page = await browser.newPage({viewport:{width:1280,height:900}});
 const errors = []; page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const u = new URL(route.request().url());
  if(u.pathname === '/') return route.fulfill({contentType:'text/html',body:html});
  if(u.pathname === '/api/studio/custom-apps' && route.request().method()==='POST') {
   assert.equal(route.request().headers()['x-pixora-trust-code'],'yes');
   assert.deepEqual(route.request().postDataBuffer(),source);
   imports++; state.cards=[card];
  } else if(u.pathname === '/api/studio/custom-apps/custom_my_message' && route.request().method()==='DELETE') {
   deletes++; state.cards=[];
  } else if(u.pathname === '/api/ha-setup') return route.fulfill({json:{ready:true}});
  return route.fulfill({json:state});
 });
 await page.goto('http://studio.test/');
 await page.getByRole('button',{name:'My Apps',exact:true}).click();
 await page.getByRole('heading',{name:'My Apps',exact:true}).waitFor();
 assert.equal(await page.getByRole('heading',{name:'Card Library',exact:true}).isVisible(),false);
 await page.getByLabel('Python card (.py, up to 256 KB)',{exact:true}).setInputFiles({name:'my_card.py',mimeType:'text/x-python',buffer:source});
 await page.getByRole('button',{name:'Import app',exact:true}).click();
 await page.getByRole('alert').filter({hasText:'Confirm that you trust'}).waitFor();
 assert.equal(imports,0);
 await page.getByLabel('I have reviewed this code and trust it to run on my HA hub.',{exact:true}).check();
 await page.getByRole('button',{name:'Import app',exact:true}).click();
 await page.getByRole('heading',{name:'My Message',exact:true}).waitFor();
 assert.equal(imports,1);
 assert.equal(await page.getByLabel('I have reviewed this code and trust it to run on my HA hub.',{exact:true}).isChecked(),false);
 await page.getByRole('button',{name:'Options & add to deck',exact:true}).filter({visible:true}).click();
 await page.getByRole('dialog').waitFor();
 assert.equal(await page.getByRole('dialog').getByLabel('Message',{exact:true}).inputValue(),'Hello Pixora');
 assert.equal(await page.getByLabel('Bright text',{exact:true}).isChecked(),true);
 await page.locator('#cancelOptions').click();
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'D:/planner/.build-tmp/led-custom-apps-desktop.png'});
 await page.setViewportSize({width:768,height:1024});
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.screenshot({path:'D:/planner/.build-tmp/led-custom-apps-tablet.png'});
 page.on('dialog',dialog=>dialog.accept());
 await page.getByRole('button',{name:'Delete app',exact:true}).click();
 await page.getByText('No custom apps imported yet.',{exact:false}).waitFor();
 assert.equal(deletes,1); assert.deepEqual(errors,[]);
 console.log('Custom apps browser passed: tab isolation, trust gate, upload, defaults, delete, no JS errors and tablet layout.');
} finally { await browser.close(); }
