import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../pixora_thermostat_controller/ui.js',import.meta.url),'utf8');
const missingRow=source.split('\n').find(line=>line.includes('for(const missing of z.openings'));
const controls=[],z={openings:['binary_sensor.missing']},selected=new Set(z.openings);
vm.runInNewContext(missingRow,{z,selected,contacts:[],list:{append:row=>controls.push(row)},check:(name,checked,change)=>({name,checked,change})});
assert.equal(controls.length,1);
controls[0].change(false);
assert.equal(z.openings.length,0);
controls[0].change(true);
assert.deepEqual(Array.from(z.openings),['binary_sensor.missing']);
controls[0].change(true);
assert.equal(z.openings.length,1);
console.log('Thermostat UI checks passed: unavailable contact deselect/reselect preserves saved protection.');
