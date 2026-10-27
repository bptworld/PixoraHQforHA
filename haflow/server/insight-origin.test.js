import test from 'node:test'
import assert from 'node:assert/strict'
import { CommandContexts, originReport, createOriginRecorder } from './insight-origin.js'

test('native command context is returned once and never guessed from states', async () => {
  const bridge = new CommandContexts(() => 101)
  const sent = []
  const result = bridge.request({ send: raw => sent.push(JSON.parse(raw)) }, { domain:'light', service:'turn_on', service_data:{entity_id:'light.kitchen'} })
  assert.equal(sent[0].type, 'call_service')
  assert.equal(bridge.accept({type:'result',id:101,success:true,result:{context:{id:'01EXACTCOMMANDCONTEXT000001'}}}), true)
  const report = originReport({reason:'Kitchen motion triggered Kitchen Lights.'},'light','turn_on',{entity_id:'light.kitchen'},await result)
  assert.equal(report.action_context,'01EXACTCOMMANDCONTEXT000001')
  assert.equal(bridge.accept({type:'result',id:101,success:true}),false)
  assert.equal(originReport(null,'light','turn_on',{entity_id:'light.kitchen'},[{context:{id:'UNRELATED'}}]).action_context,undefined)
})

test('disconnect rejects outstanding command without retry', async () => {
  const bridge = new CommandContexts(() => 102)
  let sends = 0
  const result = bridge.request({send:()=>{sends++}}, {domain:'light',service:'turn_on'})
  bridge.close()
  await assert.rejects(result,/uncertain/)
  assert.equal(sends,1)
})

test('origin report omits service payload content', () => {
  const report=originReport({reason:'HAFlow requested a notification.'},'notify','phone',{message:'SECRET',token:'SECRET'},null)
  assert.equal(report.operation,'notify.phone')
  assert.ok(!JSON.stringify(report).includes('SECRET'))
})

test('failed provenance send is not retried', async () => {
  let sends=0
  const recorder=createOriginRecorder(async()=>{sends++;throw new Error('unavailable')},()=>{})
  recorder({reason:'Test'})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(sends,1)
})

test('a failing diagnostic logger cannot escape the recorder', async () => {
  let sends=0
  const recorder=createOriginRecorder(async()=>{sends++;throw new Error('offline')},()=>{throw new Error('log unavailable')})
  recorder({reason:'First'})
  await new Promise(resolve=>setImmediate(resolve))
  recorder({reason:'Second'})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(sends,2)
})
