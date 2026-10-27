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
// Exercise the actual editor list callbacks without a browser or live HA.
function editorHarness(z){
 const roots=[];
 const node=(tag,attrs={},...children)=>({tag,attrs,children:children.flat(Infinity),replaceChildren(...items){this.children=items.flat(Infinity)}});
 const context={z,snapshot:{entities:[{id:'person.alex',name:'Alex',attributes:{}},{id:'device_tracker.phone',name:'Phone',attributes:{}},{id:'binary_sensor.window',name:'Window',attributes:{device_class:'window'}}],destinations:['notify.mobile_app_alex','notify.mobile_app_sam']},body:{append:e=>roots.push(e)},node,
 label:(name,control)=>node('label',{name},control),input:(value,change)=>({kind:'input',value,change}),picker:(name,value,rows,change)=>({kind:'picker',name,value,rows,change}),button:(name,click)=>({kind:'button',name,click}),grid:(...items)=>node('grid',{},...items),section:(name,...items)=>node('section',{name},...items),optionalSection:(name,...items)=>node('section',{name},...items),check:()=>null,targetInputs:()=>null};
 const peopleStart=source.indexOf(' const people=snapshot.entities.filter');
 const peopleEnd=source.indexOf(" body.append(section('Notification options'",peopleStart);
 const memberStart=source.indexOf(' const sources=snapshot.entities.filter');
 const memberEnd=source.indexOf(" body.append(optionalSection('Indoor temperature warnings'",memberStart);
 vm.runInNewContext(source.slice(peopleStart,peopleEnd)+source.slice(memberStart,memberEnd),context);
 const flatten=items=>items.flatMap(item=>item?[item,...flatten(item.children||[])]:[]);
 return ()=>flatten(roots);
}
const formZone={notify:{person:'Alex',service:'notify.mobile_app_alex'},household:{people:['person.alex'],away:{},enabled:false,awayMinutes:5,homeMinutes:1}};
const rendered=editorHarness(formZone);
assert.equal(formZone.notify.recipients[0].person,'Alex');
assert.equal(formZone.household.members[0].entity,'person.alex');
rendered().find(e=>e.name==='Add notification recipient').click();
assert.equal(formZone.notify.recipients.length,2);
rendered().filter(e=>e.kind==='input')[1].change('Sam');
rendered().filter(e=>e.kind==='picker'&&e.name==='HA notification destination')[1].change('notify.mobile_app_sam');
rendered().find(e=>e.name==='Remove recipient').click();
assert.equal(formZone.notify.person,'Sam');
assert.equal(formZone.notify.service,'notify.mobile_app_sam');
rendered().find(e=>e.name==='Add household member').click();
const presence=rendered().filter(e=>e.kind==='picker'&&e.name==='Home Assistant presence device')[1];
assert.ok(!presence.rows.some(([id])=>id==='binary_sensor.window'));
presence.change('device_tracker.phone');
assert.equal(formZone.household.people[1],'device_tracker.phone');
rendered().find(e=>e.name==='Remove member').click();
assert.deepEqual(Array.from(formZone.household.people),['device_tracker.phone']);
console.log('Thermostat editor checks passed: legacy selections, add/remove and device mappings.');
