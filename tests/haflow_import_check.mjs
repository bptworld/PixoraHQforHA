import assert from 'node:assert/strict'
import {spawn} from 'node:child_process'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'
import net from 'node:net'
import {fileURLToPath} from 'node:url'

const root=fileURLToPath(new URL('../haflow/',import.meta.url))
const data=await mkdtemp(path.join(process.env.HAFLOW_TEST_TMP || tmpdir(),'haflow-import-'))
const probe=net.createServer()
await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve))
const port=probe.address().port
await new Promise(resolve=>probe.close(resolve))
const server=spawn(process.execPath,['server/index.js'],{cwd:root,env:{...process.env,HAFLOW_DATA_DIR:data,PORT:String(port),SUPERVISOR_TOKEN:''},stdio:'pipe'})
let output='';server.stdout.on('data',chunk=>output+=chunk);server.stderr.on('data',chunk=>output+=chunk)
const request=async (url,body)=>{
 const response=await fetch(`http://127.0.0.1:${port}${url}`,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})
 return {status:response.status,body:await response.json()}
}
try {
 let ready=false
 for(let i=0;i<100;i++){
  try{if((await request('/health')).status===200){ready=true;break}}catch{}
  await new Promise(resolve=>setTimeout(resolve,100))
 }
 assert.ok(ready,output)
 const before=(await request('/api/backup')).body
 const graph={nodes:[{id:'trigger',type:'trigger',position:{x:20,y:30},data:{label:'Motion',entityId:'binary_sensor.motion'}}],edges:[],viewport:{x:5,y:6,zoom:0.75}}
 const backup={app:'HAFlow',version:1,flows:[{meta:{id:'default',name:before.flows[0].meta.name,paused:false},flow:graph}]}
 const first=await request('/api/backup',backup)
 assert.equal(first.status,200)
 const id=first.body.importedIds[0]
 assert.notEqual(id,'default')
 const saved=(await request('/api/backup')).body
 assert.deepEqual(saved.flows.find(f=>f.meta.id==='default'),before.flows.find(f=>f.meta.id==='default'))
 const imported=saved.flows.find(f=>f.meta.id===id)
 assert.equal(imported.meta.paused,true)
 assert.notEqual(imported.meta.name,before.flows[0].meta.name)
 assert.equal(imported.flow.nodes[0].data.entityId,'binary_sensor.motion')
 assert.deepEqual(imported.flow.viewport,graph.viewport)
 const second=await request('/api/backup',backup)
 assert.equal(second.status,200)
 assert.notEqual(second.body.importedIds[0],id)
 assert.equal((await request('/api/backup',graph)).status,200)
 const snapshot=(await request('/api/backup')).body.flows
 assert.equal((await request('/api/backup',{flows:[{flow:graph},{flow:{nodes:[]}}]})).status,400)
 assert.deepEqual((await request('/api/backup')).body.flows,snapshot)
 console.log('HAFlow import API checks passed: old backup, single flow, unique copies, paused state, preserved existing flows, invalid backup rejected without partial import')
} finally {
 server.kill()
 await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve))
 await rm(data,{recursive:true,force:true})
}
