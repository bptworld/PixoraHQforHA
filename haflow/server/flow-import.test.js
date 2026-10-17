import test from 'node:test'
import assert from 'node:assert/strict'
import {prepareFlowImport} from './flow-import.js'

const flow = {nodes:[{id:'a',type:'trigger',position:{x:10,y:20},data:{entityId:'binary_sensor.porch'}},{id:'b',type:'action',position:{x:200,y:20},data:{entityId:'light.porch'}}],edges:[{id:'ab',source:'a',target:'b',sourceHandle:'yes'}],viewport:{x:10,y:5,zoom:0.8}}
test('old backup preserves graph, references and viewport while forcing paused state',()=>{
 const backup={app:'HAFlow',version:1,flows:[{meta:{id:'porch',name:'Porch',paused:false},flow}]}
 const result=prepareFlowImport(backup)
 assert.deepEqual(result[0].flow,flow)
 assert.equal(result[0].meta.paused,true)
 assert.equal(backup.flows[0].meta.paused,false)
})
test('single old Export Flow file is accepted',()=>{
 assert.deepEqual(prepareFlowImport(flow)[0].flow,flow)
})
test('rejects invalid backups and validates later flows before any import',()=>{
 for(const invalid of [null,{}, {flows:[]},{flows:[{flow},{}]}, {...flow,edges:[{id:'bad',source:'missing',target:'b'}]}, {...flow,nodes:[flow.nodes[0],flow.nodes[0]]}]) assert.throws(()=>prepareFlowImport(invalid))
})
