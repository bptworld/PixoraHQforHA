// Test the production functions with controlled clocks/I/O. No live HA access,
// sleeps or second implementations of the runner/save logic are needed.
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import vm from 'node:vm'
import crypto from 'node:crypto'
import { variableValue, variableEntity, flowExecutionSignature } from './local-features.js'

const server = await fs.readFile(new URL('./index.js', import.meta.url), 'utf8')
const editor = await fs.readFile(new URL('../src/App.jsx', import.meta.url), 'utf8')
function fn(source, name) {
  const declarations = [...source.matchAll(/^(?:async )?function ([\w]+)\(/gm)]
  const index = declarations.findIndex(match => match[1] === name)
  assert.ok(index >= 0, `Missing production function ${name}`)
  const start=declarations[index].index
  const nextRoute=source.indexOf('\napp.',start)
  return source.slice(start,Math.min(declarations[index+1]?.index ?? source.length,nextRoute < 0 ? source.length : nextRoute))
}
function load(names, values = {}) {
  const context = vm.createContext(values)
  vm.runInContext(names.map(name => fn(server, name)).join('\n'), context)
  return context
}
function callback(name) {
  const start = editor.indexOf(`const ${name} = useCallback(`) + `const ${name} = useCallback(`.length
  const end = editor.indexOf('\n  }, [', start) + '\n  }'.length
  assert.ok(start > 0 && end > start)
  return editor.slice(start, end)
}
const deferred = () => { let resolve; const promise = new Promise(done => { resolve=done }); return { promise, resolve } }
const noOp = () => {}
const comparisons = ['getEntityComparableValue','formatComparableValue','comparisonMatches','numericComparisonMatches','entityReadingAvailable','evaluateConditionRule']

test('condition execution, preview and AND use the same live comparison variable', async () => {
  const values = {actual:{state:'10'},threshold:{state:'20'}}
  const c = load([...comparisons,'executeNode','previewNode','evaluateAndSourceNode','evaluateAndConditionRule','getConditionRules','formatPreviewOperator'], {
    getEntity: async id => values[id], throwIfCancelled:noOp, log:noOp,
  })
  const node = {id:'condition',data:{kind:'condition',entityId:'actual',value:0,operator:'greater_than',expectedVariableId:'threshold'}}
  for (const [actual, expected] of [['10',false],['30',true],['unavailable',false],['unknown',false]]) {
    values.actual.state=actual
    assert.equal(await c.executeNode(node),expected)
    assert.equal((await c.previewNode(node)).status,expected?'pass':'stop')
    assert.equal((await c.evaluateAndSourceNode(node,new Set())).passed,expected)
  }
  values.actual={state:'unavailable',attributes:{power:100}};node.data.attribute='power'
  assert.equal(await c.executeNode(node),false)
  assert.equal((await c.previewNode(node)).status,'stop')
})

function timerContext(getEntity) {
  const callbacks=[], fired=[]
  const c=load([...comparisons,'getStateTriggerRules','getTriggerDurationMs','stateTriggerMatches','hasStateFilter','durationRuleMatches','updatePendingStateTriggerTimers','clearPendingStateTriggerTimers','formatPreviewOperator','formatTriggerDuration'], {
    COMPARISON_OPERATORS:new Set(['equals','greater_than']), pendingStateTriggerTimers:new Map(), config:{runnerEnabled:true}, getEntity,
    setTimeout:callback=>{const timer={callback};callbacks.push(timer);return timer},clearTimeout:noOp,
    getEntityDeviceId:noOp,ANY_CHANGE:'__changed__',triggerNode:async(...args)=>{fired.push(args)},log:noOp,
  })
  const node={id:'t',data:{kind:'state',entityId:'sensor.power',attribute:'power',operator:'greater_than',value:5,duration:1,durationUnit:'seconds'}}
  const entry={meta:{id:'flow',name:'Test'},flow:{nodes:[node]}}
  const event={event_type:'state_changed',data:{entity_id:'sensor.power',old_state:{state:'on',attributes:{power:0}},new_state:{state:'on',attributes:{power:10}}}}
  return {c,callbacks,fired,entry,event}
}

test('unavailable previous readings and whitespace cannot suppress or satisfy numeric entries', () => {
  const {c,entry,event}=timerContext(async()=>null)
  event.data.old_state={state:'unavailable',attributes:{power:100}}
  assert.equal(c.stateTriggerMatches(entry.flow.nodes[0].data,event.data,true),true)
  for (const value of ['', '  ',null,undefined,false]) assert.equal(c.numericComparisonMatches(value,'equals',0),false)
})

test('recovery reads HA once per recovery request, not on every periodic tick', async () => {
  let reads=0,armed=0
  const entry={meta:{id:'flow'},flow:{nodes:[{id:'t',data:{kind:'state',entityId:'sensor.power',value:5}}]}}
  const c=load(['recoverDurationTriggers'],{recoveryBusy:false,durationRecoveryRequested:true,config:{runnerEnabled:true},haSocket:{readyState:1},WebSocket:{OPEN:1},
    getRunnableFlowEntries:async()=>[entry],getStateTriggerRules:d=>[d],getTriggerDurationMs:()=>100,variables:[],variableEntity,
    haRest:async()=>{reads++;return[{entity_id:'sensor.power',state:'10'}]},flowExecutionSignature,durationRuleMatches:()=>true,pendingStateTriggerTimers:new Map(),
    updatePendingStateTriggerTimers:()=>{armed++},clearTimeout:noOp,
  })
  await c.recoverDurationTriggers();await c.recoverDurationTriggers()
  assert.equal(reads,1);assert.equal(armed,1)
  c.durationRecoveryRequested=true;await c.recoverDurationTriggers()
  assert.equal(reads,2)
})

test('duration callbacks reject unavailable entities even with stale numeric attributes', async () => {
  for(const state of ['unavailable','unknown',null]) {
    const {c,callbacks,fired,entry,event}=timerContext(async()=>({state,attributes:{power:100}}))
    c.updatePendingStateTriggerTimers(entry,event)
    await callbacks[0].callback()
    assert.equal(fired.length,0)
    assert.equal(c.pendingStateTriggerTimers.size,0)
  }
})
test('in-flight duration reads cannot resurrect a paused or replaced timer', async () => {
  const reading=deferred()
  const {c,callbacks,fired,entry,event}=timerContext(()=>reading.promise)
  c.updatePendingStateTriggerTimers(entry,event)
  const old=callbacks[0].callback()
  c.clearPendingStateTriggerTimers('flow')
  c.updatePendingStateTriggerTimers(entry,event)
  const replacement=c.pendingStateTriggerTimers.values().next().value
  reading.resolve(event.data.new_state)
  await old
  assert.equal(fired.length,0)
  assert.equal(c.pendingStateTriggerTimers.values().next().value,replacement)
  c.config.runnerEnabled=false
  await callbacks[1].callback()
  assert.equal(fired.length,0)
})
test('matching updates retain a hold after its From transition and recovery starts a full hold', () => {
  const {c,callbacks,entry,event}=timerContext(async()=>event.data.new_state)
  entry.flow.nodes[0].data.from='0'
  c.updatePendingStateTriggerTimers(entry,event)
  assert.equal(callbacks.length,1)
  const updated={...event,data:{...event.data,old_state:event.data.new_state,new_state:{state:'on',attributes:{power:12}}}}
  c.updatePendingStateTriggerTimers(entry,updated)
  assert.equal(callbacks.length,1)
  c.clearPendingStateTriggerTimers('flow')
  c.updatePendingStateTriggerTimers(entry,{...updated,data:{...updated.data,old_state:null}},{recovering:true})
  assert.equal(callbacks.length,2)
})

test('queued variable mutations stop on cancellation instead of triggering other flows', async () => {
  const gate=deferred(), writes=[]
  const c=load(['variableTransaction','changeVariable','executeNode','throwIfCancelled','createCancelledError'], {
    variables:[{id:'a',name:'Active',type:'boolean',value:false}],variableWrites:gate.promise,crypto,variableValue,variableEntity,
    variablesPath:'unused',writeJson:async(...args)=>writes.push(args),broadcast:noOp,setImmediate:noOp,log:noOp,
  })
  const controller=new AbortController()
  const operation=c.executeNode({data:{kind:'variable',variableId:'haflow_variable.a',variableValue:true}},{signal:controller.signal})
  controller.abort();gate.resolve()
  await assert.rejects(operation,{name:'AbortError'})
  assert.equal(writes.length,0)
  assert.equal(c.variables[0].value,false)
})
test('a Wait cancelled during its initial reading does not subscribe or block its replacement', async () => {
  const reading=deferred();let subscribed=false
  const c=load(['waitForEntityState','throwIfCancelled','createCancelledError','getEntityComparableValue','formatComparableValue'], {
    getEntity:()=>reading.promise,waiters:[],setTimeout:()=>{subscribed=true;return 1},clearTimeout:noOp,
  })
  const controller=new AbortController()
  const operation=c.waitForEntityState('sensor.test','state','on',300,controller.signal)
  controller.abort();reading.resolve({state:'off'})
  await assert.rejects(operation,{name:'AbortError'})
  assert.equal(subscribed,false)
  assert.equal(c.waiters.length,0)
})
test('an in-flight catalog read cannot restore a paused flow into the runnable cache', async () => {
  const reading=deferred(),started=deferred();let reads=0
  const c=load(['getRunnableFlowEntries','invalidateRunnableFlowCache'], {
    runnableFlowCache:null,runnableFlowGeneration:0,config:{activeFlowId:'default'},cachedFlow:{nodes:[],edges:[]},
    readFlowIndex:async()=>{reads++;if(reads===1){started.resolve();return reading.promise}return[{id:'flow',paused:true}]},readFlow:async()=>({nodes:[],edges:[]}),
  })
  const operation=c.getRunnableFlowEntries();await started.promise
  c.invalidateRunnableFlowCache();reading.resolve([{id:'flow',paused:false}])
  assert.equal((await operation).length,0)
  assert.equal(c.runnableFlowCache.length,0)
  assert.equal(reads,2)
})
test('cancelling during temporary file I/O prevents the atomic commit', async () => {
  const writing=deferred(),started=deferred();let renamed=false
  const c=load(['writeJson','throwIfCancelled','createCancelledError'], {
    fileWrites:new Map(),crypto,fs:{writeFile:async()=>{started.resolve();await writing.promise},rename:async()=>{renamed=true},rm:async()=>{}},
  })
  const controller=new AbortController()
  const operation=c.writeJson('test.json',{value:true},{signal:controller.signal})
  await started.promise;controller.abort();writing.resolve()
  await assert.rejects(operation,{name:'AbortError'})
  assert.equal(renamed,false)
})
test('label and layout saves retain holds; functional graph edits clear old callbacks', async () => {
  let clears=0
  const original={nodes:[{id:'t',position:{x:0,y:0},data:{kind:'state',label:'Old',entityId:'sensor.power',value:5,duration:5}}],edges:[]}
  const c=load(['writeFlow'],{readJson:async()=>original,getFlowPath:x=>x,writeJson:async()=>{},normalizeFlow:x=>x,flowExecutionSignature,clearPendingStateTriggerTimers:()=>{clears++},invalidateRunnableFlowCache:noOp})
  const renamed=structuredClone(original);renamed.nodes[0].data.label='New';renamed.nodes[0].position.x=200
  await c.writeFlow('flow',renamed);assert.equal(clears,0)
  const edited=structuredClone(original);edited.nodes[0].data.value=6
  await c.writeFlow('flow',edited);assert.equal(clears,1)
  const linked=structuredClone(original);linked.edges.push({source:'t',target:'new'})
  await c.writeFlow('flow',linked);assert.equal(clears,2)
})

function saveContext(apiFetch) {
  return vm.createContext({hasLoadedFlow:true,currentFlowIdRef:{current:'original'},currentGraphRef:{current:JSON.stringify({nodes:[{label:'B'}],edges:[]})},lastSavedSnapshotRef:{current:''},
    lastSavedViewportRef:{current:{}},saveQueueRef:{current:Promise.resolve()},pendingSavesRef:{current:0},viewportRef:{current:{}},normalizeViewport:x=>x,getViewport:()=>({}),apiFetch,
    setSaveStatus:noOp,setSaveRevision:noOp,setLogs:noOp})
}
test('an old save callback reads the newest graph instead of overwriting it with its closure', async () => {
  const requests=[], first=deferred()
  const c=saveContext(async(url,options)=>{const graph=JSON.parse(options.body);requests.push(graph);if(requests.length===1)await first.promise;return{json:async()=>({message:'saved'})}})
  const make=vm.runInContext(`activeFlowId => (${callback('saveFlow')})`,c)
  const stale=make('original'), latest=make('original')
  const flush=latest({silent:true});await Promise.resolve()
  const delayedViewportSave=stale({silent:true})
  first.resolve();await flush;await delayedViewportSave
  assert.deepEqual(requests.map(graph=>graph.nodes[0].label),['B','B'])
  c.currentFlowIdRef.current='different'
  await stale({silent:true})
  assert.equal(requests.length,2)
})
test('saving before initial loading finishes never writes the example graph', async () => {
  let writes=0
  const c=saveContext(async()=>{writes++;return{json:async()=>({})}})
  c.hasLoadedFlow=false
  await vm.runInContext(`activeFlowId => (${callback('saveFlow')})`,c)('original')({silent:true})
  assert.equal(writes,0)
})
test('save serialization includes response parsing and retains a newer viewport', async () => {
  const body=deferred(),entered=deferred();let count=0
  const c=saveContext(async()=>{count++;return{json:async()=>{if(count===1){entered.resolve();await body.promise}return{message:'saved'}}}})
  const save=vm.runInContext(`activeFlowId => (${callback('saveFlow')})`,c)('original')
  const first=save({silent:true});await entered.promise
  const second=save({silent:true});await Promise.resolve()
  assert.equal(count,1)
  c.viewportRef.current={x:999};body.resolve();await first;await second
  assert.equal(c.viewportRef.current.x,999)
  assert.equal(c.pendingSavesRef.current,0)
})
test('a flow switch cancels the viewport timer before waiting on a save', async () => {
  const start=editor.indexOf('const loadFlow = ')+ 'const loadFlow = '.length
  const end=editor.indexOf('\n  const createFlow = ',start)
  let cleared=false
  const c=vm.createContext({viewportSaveTimeoutRef:{current:1},window:{clearTimeout:()=>{cleared=true},requestAnimationFrame:noOp},hasLoadedFlow:true,
    currentGraphRef:{current:'new'},lastSavedSnapshotRef:{current:'old'},viewportRef:{current:{}},lastSavedViewportRef:{current:{}},
    saveFlow:async()=>{assert.ok(cleared)},saveQueueRef:{current:Promise.resolve()},apiFetch:async()=>({json:async()=>({nodes:[],edges:[]})}),normalizeViewport:x=>x||{},normalizeRuntimeSnapshot:x=>x,
    setHasLoadedFlow:noOp,setSaveStatus:noOp,setActiveFlowId:noOp,setNodes:noOp,setEdges:noOp,setViewport:noOp,setSelectedId:noOp,setSelectedNodeIds:noOp,setSelectedEdgeId:noOp,setNodeRuntime:noOp,resetHistory:noOp})
  await vm.runInContext(`(${editor.slice(start,end).trim()})`,c)('different')
})
test('Trigger to Set variable is a valid terminal action path', () => {
  const declaration=editor.match(/^const NODE_KINDS_REQUIRING_OUTGOING = .*$/m)[0]
  const c=vm.createContext({validateNodeData:()=>'',shouldSuppressNodeValidation:()=>false})
  vm.runInContext(declaration+'\n'+fn(editor,'validateFlow'),c)
  const issues=c.validateFlow([{id:'t',data:{kind:'voice',phrase:'Night'}},{id:'v',data:{kind:'variable',variableId:'haflow_variable.a',variableValue:true}}],[{source:'t',target:'v'}])
  assert.equal(issues.length,0)
})
