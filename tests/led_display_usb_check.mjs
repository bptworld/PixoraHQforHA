import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../tools/display_usb_entry.js',import.meta.url),'utf8').replace("import {ESPLoader,Transport} from 'esptool-js';",'const {ESPLoader,Transport}=globalThis.usbFixture;');
let writes=0,resets=0,disconnected=0,chip='ESP32-S3',md5='expected';
class Transport{constructor(port,tracing){assert.equal(tracing,false)}async disconnect(){disconnected++}}
class ESPLoader{constructor(){this.chip={CHIP_NAME:chip}}async main(){}async writeFlash(options){writes++;assert.equal(options.fileArray[0].address,0);assert.equal(options.eraseAll,false);assert.equal(options.flashSize,'keep')}async flashMd5sum(){return md5}async after(mode){assert.equal(mode,'hard_reset');resets++}}
globalThis.usbFixture={Transport,ESPLoader};const {installUsb}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const download=async()=>({headers:new Map([['X-Firmware-MD5','expected']]),arrayBuffer:async()=>new Uint8Array(1024).buffer});
await installUsb({},download,()=>{});assert.equal(writes,1);assert.equal(resets,1);
chip='ESP32';await assert.rejects(installUsb({},()=>{throw Error('Wrong-chip download')},()=>{}),/S3 only/);assert.equal(writes,1);
chip='ESP32-S3';md5='mismatch';await assert.rejects(installUsb({},download,()=>{}),/verification failed/);assert.equal(writes,2);assert.equal(resets,1);assert.equal(disconnected,3);
console.log('Browser USB contract passed: S3 chip guard, exact configured bytes, flash verification before reset, no automatic retry, no packet tracing and disconnect on failures.');
