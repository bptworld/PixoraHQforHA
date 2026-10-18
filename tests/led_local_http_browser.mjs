// Real local HTTP (no intercepted requests), including the HA ingress iframe path.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
const require=createRequire(process.env.PLAYWRIGHT_PACKAGE||'D:/planner/connect-features/cloud/render/planner/package.json');
const {chromium}=require('playwright');
const html=readFileSync(new URL('../pixora_led_displays/studio.html',import.meta.url));
const prefix='/api/hassio_ingress/local-test/';
const state={cards:[],decks:{},devices:{},groups:{},graphics:{},settings:{},runtime:{},displays:[]};
let studioReads=0,unexpected=0;
const server=createServer((req,res)=>{
 const path=new URL(req.url,'http://test').pathname;
 if(path==='/app/pixora_led_displays'){res.setHeader('Content-Type','text/html');return res.end(`<iframe title="Studio" src="${prefix}"></iframe>`)}
 if(path===prefix){res.setHeader('Content-Type','text/html');return res.end(html)}
 if(path===prefix+'api/studio'){studioReads++;assert.equal(req.headers['content-type'],'application/json');res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(state))}
 if(path===prefix+'api/automation-status'){res.setHeader('Content-Type','application/json');return res.end('{}')}
 if(path==='/favicon.ico'){res.statusCode=204;return res.end()}
 unexpected++;res.statusCode=404;res.end();
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const browser=await chromium.launch({args:['--host-resolver-rules=MAP homeassistant.test 127.0.0.1','--no-proxy-server']});
try{
 const page=await browser.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const base=`http://homeassistant.test:${server.address().port}`;
 await page.goto(base+'/app/pixora_led_displays');
 const ui=page.frameLocator('iframe');
 await ui.getByRole('button',{name:'My Apps',exact:true}).click();
 await ui.getByRole('heading',{name:'My Apps',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>window.isSecureContext),false);
 await page.reload();
 await ui.getByRole('button',{name:'My Apps',exact:true}).click();
 await ui.getByRole('heading',{name:'My Apps',exact:true}).waitFor();
 assert.ok(studioReads>=2);assert.equal(unexpected,0);assert.deepEqual(errors,[]);
 console.log('Real local HTTP ingress passed: insecure HTTP, normal/reloaded iframe, unchanged JSON request headers and no cloud requests.');
}finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
