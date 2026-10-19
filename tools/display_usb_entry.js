import {ESPLoader,Transport} from 'esptool-js';
export async function installUsb(port,download,status){
 const transport=new Transport(port,false);let loader;
 try{
  status('Connecting to the controller…');
  loader=new ESPLoader({transport,baudrate:460800,terminal:{clean(){},writeLine(){},write(){}}});
  await loader.main();
  if(loader.chip.CHIP_NAME!=='ESP32-S3')throw Error('This installer supports MatrixPortal S3 only. No flash write was started.');
  const response=await download();const expected=response.headers.get('X-Firmware-MD5');
  const bytes=new Uint8Array(await response.arrayBuffer());let binary='';
  for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
  await loader.writeFlash({fileArray:[{data:binary,address:0}],flashSize:'keep',flashMode:'keep',flashFreq:'keep',eraseAll:false,compress:true,reportProgress:(file,written,total)=>status('Installing — keep USB connected.',Math.round(100*written/total))});
  status('Verifying the installed firmware…');
  const actual=await loader.flashMd5sum(0,bytes.length);
  if(actual.toLowerCase()!==expected)throw Error('USB verification failed. Check the controller before trying again. It was not retried.');
  await loader.after('hard_reset');
 }finally{await transport.disconnect().catch(()=>{})}
}
