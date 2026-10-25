// Exercise the real app against isolated temporary storage. No live HA calls.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import net from 'node:net'
import { spawn } from 'node:child_process'
import { setTimeout as sleep } from 'node:timers/promises'

test('local variables, exact voice, overlapping retriggers, pause and backup retain real data', {timeout:30000}, async t => {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(),'haflow-regression-'))
  const socket = net.createServer(); await new Promise(r => socket.listen(0,'127.0.0.1',r)); const port = socket.address().port; await new Promise(r => socket.close(r))
  await fs.writeFile(path.join(folder,'config.json'),JSON.stringify({runnerEnabled:true}))
  const child = spawn(process.execPath,['server/index.js'], {cwd:path.resolve(import.meta.dirname,'..'), env:{...process.env,HAFLOW_DATA_DIR:folder,PORT:String(port),SUPERVISOR_TOKEN:''},stdio:['ignore','pipe','pipe']})
  let output=''; child.stdout.on('data',data=>{output+=data}); child.stderr.on('data',data=>{output+=data})
  t.after(async()=>{child.kill(); await new Promise(r=>child.exitCode !== null ? r() : child.once('exit',r)); await fs.rm(folder,{recursive:true,force:true})})
  const api = async (url, body, method=body?'POST':'GET') => {
    const response = await fetch(`http://127.0.0.1:${port}${url}`,{method,headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined})
    const result=await response.json(); assert.ok(response.ok,JSON.stringify(result)); return result
  }
  let ready=false
  for(let i=0;i<160;i++){try{await api('/api/variables');ready=true;break}catch{if(child.exitCode!==null)assert.fail(output);await sleep(50)}}
  assert.ok(ready,output || 'The isolated server did not start.')
  const variable=(await api('/api/variables',{name:'Dryer',type:'boolean',value:false})).variable
  const valueRef=`haflow_variable.${variable.id}`
  const created=(await api('/api/flows',{name:'Local regression'})).flow
  const graph={nodes:[{id:'t',data:{kind:'voice',phrase:'Good night'}},{id:'u',data:{kind:'voice',phrase:'Bedtime'}},{id:'d',data:{kind:'delay',seconds:.3}},{id:'v',data:{kind:'variable',variableId:valueRef,variableValue:true}},{id:'independent',data:{kind:'voice',phrase:'Separate'}},{id:'long',data:{kind:'delay',seconds:.8}},{id:'end',data:{kind:'debug',message:'Independent done'}}],edges:[{id:'a',source:'t',target:'d'},{id:'b',source:'u',target:'d'},{id:'c',source:'d',target:'v'},{id:'e',source:'independent',target:'long'},{id:'f',source:'long',target:'end'}],viewport:{x:12,y:34,zoom:.7}}
  await api(`/api/flows/${created.id}`,graph,'PUT')
  const preview=await api('/api/node-preview',{node:graph.nodes.find(n=>n.id==='v'),nodes:graph.nodes,edges:graph.edges})
  assert.match(preview.details.join(' '),/Nothing was changed/)
  assert.equal((await api('/api/variables')).variables[0].value,false)
  assert.match((await api('/api/node-preview',{node:graph.nodes[0]})).details.join(' '),/starts no flow/)
  assert.equal((await api('/api/voice/trigger',{phrase:'Not good night',requestId:'no'})).matched,0)
  await api('/api/voice/trigger',{phrase:'Separate',requestId:'separate'})
  await api('/api/voice/trigger',{phrase:'Good night!',requestId:'first'})
  await sleep(70)
  await api('/api/voice/trigger',{phrase:'Bedtime',requestId:'second'})
  assert.equal((await api('/api/voice/trigger',{phrase:'Bedtime',requestId:'second'})).duplicate,true)
  await sleep(1050)
  assert.equal((await api('/api/variables')).variables[0].value,true)
  let history=(await api('/api/run-history')).history
  assert.ok(history.some(r=>r.status==='cancelled'))
  assert.ok(history.some(r=>r.status==='completed' && r.trigger.includes('voice: separate')),JSON.stringify(history))
  await api('/api/variables',{id:variable.id,value:false})
  await api('/api/voice/trigger',{phrase:'Good night',requestId:'pause'})
  await api('/api/flows/default') // pausing must work even with a different editor open
  await api(`/api/flows/${created.id}/pause`,{paused:true},'PATCH')
  await sleep(500)
  assert.equal((await api('/api/variables')).variables[0].value,false)
  const power=(await api('/api/variables',{name:'Power',type:'number',value:0})).variable
  const threshold=(await api('/api/variables',{name:'Threshold',type:'number',value:5})).variable
  const held=(await api('/api/variables',{name:'Held',type:'boolean',value:false})).variable
  const heldFlow=(await api('/api/flows',{name:'Hold regression'})).flow
  await api(`/api/flows/${heldFlow.id}`,{nodes:[{id:'power',data:{kind:'state',entityId:`haflow_variable.${power.id}`,operator:'greater_than',value:5,duration:.15,durationUnit:'seconds'}},{id:'compare',data:{kind:'condition',entityId:`haflow_variable.${power.id}`,operator:'greater_than',value:0,expectedVariableId:`haflow_variable.${threshold.id}`}},{id:'held',data:{kind:'variable',variableId:`haflow_variable.${held.id}`,variableValue:true}}],edges:[{id:'p',source:'power',target:'compare'},{id:'h',source:'compare',target:'held',sourceHandle:'true'}]},'PUT')
  await api('/api/variables',{id:power.id,value:9})
  await sleep(50)
  await api('/api/variables',{id:power.id,value:4})
  await sleep(220)
  assert.equal((await api('/api/variables')).variables.find(v=>v.id===held.id).value,false)
  await api('/api/variables',{id:power.id,value:9})
  await sleep(60)
  await api('/api/variables',{id:power.id,value:10}) // no reset while comparison holds
  await sleep(200)
  assert.equal((await api('/api/variables')).variables.find(v=>v.id===held.id).value,true)
  const duplicates=await Promise.all([1,2].map(()=>api('/api/voice/trigger',{phrase:'Separate',requestId:'concurrent'})))
  assert.equal(duplicates.filter(r=>r.duplicate).length,1)
  const backup=await api('/api/backup')
  assert.equal(backup.variables[0].value,false)
  const saved=backup.flows.find(f=>f.meta.id===created.id).flow
  assert.deepEqual(saved.viewport,graph.viewport)
  assert.equal(saved.nodes.find(n=>n.id==='v').data.variableId,valueRef)
  const imported=await api('/api/backup',backup)
  assert.ok(imported.importedIds.length)
  assert.ok(imported.flows.filter(f=>imported.importedIds.includes(f.id)).every(f=>f.paused))
  assert.equal((await api('/api/variables')).variables.length,4)
  await api(`/api/flows/${created.id}`,undefined,'DELETE')
  const staleSave=await fetch(`http://127.0.0.1:${port}/api/flows/${created.id}`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(graph)})
  assert.equal(staleSave.status,404)
  await assert.rejects(fs.access(path.join(folder,'flows',`${created.id}.json`)))
  assert.equal((await api('/api/runner')).enabled,true)
  await api('/api/runner',{enabled:false},'PUT')
  assert.equal(JSON.parse(await fs.readFile(path.join(folder,'config.json'),'utf8')).runnerEnabled,false)
})
