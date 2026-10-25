import test from 'node:test'
import assert from 'node:assert/strict'
import { variableValue, variableEntity, validatePhrase, normalizePhrase, reachable, overlapping, importVariables } from './local-features.js'

test('typed variables reject unknown booleans, non-finite numbers and oversized text', () => {
  assert.equal(variableValue('boolean', 'false'), false)
  assert.equal(variableValue('number', '12.5'), 12.5)
  assert.equal(variableEntity({id:'a', name:'Test', type:'boolean', value:false}).state, 'false')
  for (const [type, value] of [['boolean', 'off'], ['number', ''], ['number', ' '], ['number', [1]], ['number', true], ['number', 'NaN'], ['text', 'x'.repeat(2001)]]) assert.throws(() => variableValue(type, value))
})
test('voice matching is exact, with punctuation and whitespace normalization only', () => {
  assert.equal(validatePhrase('Good night!'), normalizePhrase(' GOOD   NIGHT '))
  assert.equal(validatePhrase('Good night!  '), normalizePhrase(' GOOD   NIGHT '))
  assert.notEqual(normalizePhrase('not good night'), validatePhrase('Good night'))
  for (const value of ['', '*', '{anything}', 'a'.repeat(101)]) assert.throws(() => validatePhrase(value))
})
test('shared downstream nodes overlap; independent paths remain independent, including cycles', () => {
  const flow = {edges:[{source:'a',target:'x'},{source:'b',target:'x'},{source:'c',target:'y'},{source:'x',target:'a'}]}
  assert.equal(overlapping(reachable(flow,'a'), reachable(flow,'b')), true)
  assert.equal(overlapping(reachable(flow,'a'), reachable(flow,'c')), false)
  assert.deepEqual([...reachable(flow,'a')].sort(), ['a','x'])
})
test('backup imports never overwrite a current variable; conflicting references are remapped', () => {
  const existing = [{id:'one',name:'Motion',type:'boolean',value:true}]
  const graph = [{flow:{nodes:[{data:{entityId:'haflow_variable.one',variableId:'haflow_variable.one',expectedVariableId:'haflow_variable.one',message:'haflow_variable.one'}}]}}]
  const result = importVariables([{id:'one',name:'Motion',type:'boolean',value:false}],existing,graph)
  assert.equal(result.variables[0].value,true)
  assert.equal(result.variables[1].value,false)
  assert.equal(result.variables[1].name,'Motion (2)')
  const data = result.flows[0].flow.nodes[0].data
  assert.equal(data.entityId, `haflow_variable.${result.variables[1].id}`)
  assert.equal(data.variableId,data.entityId)
  assert.equal(data.expectedVariableId,data.entityId)
  assert.equal(data.message,'haflow_variable.one')
  assert.deepEqual(importVariables(undefined,existing,graph).flows,graph)
  assert.throws(() => importVariables([{id:'bad',name:'x',type:'number',value:'unknown'}],existing,graph))
  assert.throws(() => importVariables([{name:'x',type:'boolean',value:false}],existing,graph))
})
