'use strict';
let snapshot=null,cursor=null,busy=false,filter={entity:'',search:'',kind:''},sequence=0,exclusionDraft=[];
const $=id=>document.getElementById(id);
function node(tag,attrs={},...children){const e=document.createElement(tag);for(const[k,v]of Object.entries(attrs)){if(k.startsWith('on'))e.addEventListener(k.slice(2).toLowerCase(),v);else if(k in e)e[k]=v;else e.setAttribute(k,v)}for(const c of children.flat(Infinity)){if(c===null||c===undefined||c===false)continue;e.append(c instanceof Node?c:document.createTextNode(String(c)))}return e}
async function api(path,body){const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Pixora-Request':'1'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});if(!response.ok){let error='The request could not be completed.';try{error=(await response.json()).error||error}catch{}throw Error(error)}return response.json()}
function when(at){try{return new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'medium',hour12:true,timeZone:snapshot?.timezone||'UTC'}).format(new Date(at))}catch{return at}}
function message(text){$('message').textContent=text;$('message').hidden=!text}
const labels={state_changed:'Reported change',call_service:'Command requested',automation_triggered:'Automation started',script_started:'Script started',pixora_insight:'App-reported explanation',coverage:'Recording coverage'};
function eventCard(event){return node('article',{className:'event'},node('div',{},node('span',{className:'badge'},labels[event.kind]||event.kind),node('h3',{},event.title),node('time',{},when(event.at)),node('p',{},event.entities.join(' · ')||'No individual entity target recorded')),event.kind==='coverage'?null:node('button',{type:'button',onClick:()=>explain(event.id)},'Explain'))}
function renderStatus(data){snapshot=data;$('connection').textContent=data.connected?'Recording locally':'Reconnecting';$('version').textContent='v'+data.version+' · '+data.timezone;const health=$('health');health.className='coverage'+(!data.connected||data.storageError||data.dropped?' warning':'');health.textContent=data.storageError||data.notice;health.append(node('p',{className:'fine'},`${data.count.toLocaleString()} events retained · ${(data.databaseBytes/1048576).toFixed(1)} MB · Up to ${data.settings.days} days / ${data.settings.limit.toLocaleString()} events`));if(data.dropped)health.append(node('p',{},data.dropped+' events could not be recorded in this app session. Check recording coverage for gaps.'));if(!data.registryReady)health.append(node('p',{className:'fine'},'Device/area target mapping is not fully available; explicit entity targets and state changes still record.'));const select=$('entity'),selected=select.value;select.replaceChildren(node('option',{value:''},'All devices and entities'),...data.entities.map(e=>node('option',{value:e.id},e.name+' · '+e.id)));if(selected&&!data.entities.some(e=>e.id===selected))select.append(node('option',{value:selected},selected+' (not in current catalog)'));select.value=selected}
async function load(older=false){if(busy)return;busy=true;const current=++sequence;try{const params=new URLSearchParams(filter);if(older&&cursor)params.set('before',String(cursor));const [status,result]=await Promise.all([api('api/status'),api('api/events?'+params)]);if(current!==sequence)return;renderStatus(status);if(!older)$('events').replaceChildren();$('events').append(...result.events.map(eventCard));cursor=result.next;$('older').hidden=!cursor;$('summary').textContent=older?'Showing retained activity, newest first.':'Recent activity · newest first';if(!$('events').children.length)$('events').append(node('div',{className:'empty'},node('h3',{},'No recorded activity matches yet'),node('p',{},'Recording starts when Insight connects. Try another device or wait for its next change.')));message('')}catch(e){message(e.message)}finally{busy=false}}
function detailsView(event){
 const details=event.details,rows=[];
 if(event.kind==='state_changed'){
  for(const [label,value] of [['Before',details.before],['After',details.after]]){rows.push(node('p',{},node('strong',{},label+': '),value?.state??'Not present'));for(const [key,v] of Object.entries(value?.attributes||{}))rows.push(node('p',{className:'fine'},key.replaceAll('_',' ')+': '+(Array.isArray(v)?v.join(', '):v??'Not reported')))}
 }else if(event.kind==='call_service'){rows.push(node('p',{},'Action requested: '+details.service));for(const [key,v] of Object.entries(details.settings||{}))rows.push(node('p',{className:'fine'},key.replaceAll('_',' ')+': '+(Array.isArray(v)?v.join(', '):v??'Not reported')));if(details.content)rows.push(node('p',{className:'fine'},details.content))}
 else if(event.kind==='pixora_insight')rows.push(node('p',{},details.reason));
 return node('div',{},...rows,node('details',{className:'technical'},node('summary',{},'Technical details'),node('pre',{},JSON.stringify(details,null,2))));
}
function exclusionControls(event,devices=[]){
 const display=event.kind==='pixora_insight'&&event.details.source&&event.details.targetName;
 const targets=[...event.entities,...devices.map(d=>"device:"+d.id)];
 if(display)targets.push('app-target:'+event.details.source+' / '+event.details.targetName);
 const rows=targets.map(entity=>{
  const isDisplay=entity.startsWith('app-target:'),isDevice=entity.startsWith('device:'),label=isDevice?'Device':isDisplay?'Display':'Entity';
  let excluded=!!snapshot?.settings.excluded.includes(entity);
  const status=node('p',{className:'fine',role:'status'},excluded?'Already excluded from future recording.':'Stops future recording; earlier history stays available.'),control=node('button',{type:'button',disabled:false},excluded?'Restore '+label.toLowerCase():'Exclude '+label.toLowerCase());
  control.onclick=async()=>{control.disabled=true;try{const result=await api('api/exclude',{entity,restore:excluded});if(snapshot)snapshot.settings=result.settings;excluded=!excluded;control.textContent=(excluded?'Restore ':'Exclude ')+label.toLowerCase();control.disabled=false;status.textContent=excluded?'Excluded from future recording. Earlier history stays available.':'Restored. Future activity will be recorded.'}catch(e){control.disabled=false;status.textContent=e.message}};
  return node('div',{className:'exclusion-row'},node('span',{className:'fine'},isDevice?(devices.find(d=>'device:'+d.id===entity)?.name||entity):isDisplay?event.details.targetName:entity),control,status);
 });
 return rows.length?node('section',{className:'exclusion-controls','aria-label':'Entity recording options'},...rows):null;
}
async function explain(id){$('explanation-body').replaceChildren(node('p',{},'Reading the recorded evidence…'));$('explanation').showModal();try{const result=await api('api/explain/'+id);$('explanation-body').replaceChildren(node('h3',{},result.event.title),node('p',{},when(result.event.at)),node('p',{},result.answer),...([exclusionControls(result.event,result.devices)].filter(Boolean)),node('h3',{},'Recorded details'),detailsView(result.event),node('h3',{},'Linked evidence'),result.evidence.length?node('ol',{},...result.evidence.map(row=>node('li',{},node('strong',{},row.title),node('p',{className:'fine'},when(row.at))))):node('p',{},'No additional causal links were retained.'),node('p',{className:'fine'},result.note))}catch(e){$('explanation-body').replaceChildren(node('p',{},e.message))}}
$('apply').onclick=()=>{if(busy)return;filter={entity:$('entity').value,search:$('search').value.trim(),kind:$('kind').value};cursor=null;load()};$('search').addEventListener('keydown',e=>{if(e.key==='Enter')$('apply').click()});$('refresh').onclick=()=>load();$('older').onclick=()=>{$('live').checked=false;load(true)};$('explanation-close').onclick=()=>$('explanation').close();$('settings-close').onclick=()=>$('settings').close();function renderExclusions(){
 const entities=exclusionDraft.filter(key=>!key.startsWith('device:')&&!key.startsWith('app-target:'));
 $('excluded').replaceChildren(...entities.map(key=>node('option',{value:key},key)));
 $('restore-entity').disabled=true;
 const devices=exclusionDraft.filter(key=>key.startsWith('device:')||key.startsWith('app-target:'));
 $('restore-list').replaceChildren(...devices.map(key=>{
  const button=node('button',{type:'button'},'Restore');
  button.onclick=()=>{exclusionDraft=exclusionDraft.filter(value=>value!==key);renderExclusions();$('settings-error').textContent='Save settings to apply restoration.'};
  return node('div',{className:'exclusion-row'},node('span',{},key.replace(/^app-target:/,'').replace(/^device:/,'Device: ')),button);
 }));
 $('device-exclusions').hidden=!devices.length;
}
$('excluded').onchange=()=>{$('restore-entity').disabled=!$('excluded').selectedOptions.length};
$('restore-entity').onclick=()=>{
 const selected=new Set(Array.from($('excluded').selectedOptions,option=>option.value));
 exclusionDraft=exclusionDraft.filter(key=>!selected.has(key));renderExclusions();
 $('settings-error').textContent='Save settings to apply restoration.';
};
$('settings-open').onclick=()=>{if(!snapshot)return;$('days').value=snapshot.settings.days;$('limit').value=snapshot.settings.limit;exclusionDraft=[...snapshot.settings.excluded];renderExclusions();$('settings-error').textContent='';$('settings').showModal()};
$('settings-form').onsubmit=async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;try{await api('api/settings',{days:Number($('days').value),limit:Number($('limit').value),excluded:exclusionDraft});$('settings').close();await load()}catch(e){$('settings-error').textContent=e.message}finally{submit.disabled=false}};
load();setInterval(()=>{if(!document.hidden&&$('live').checked&&!$('settings').open&&!$('explanation').open&&!document.activeElement?.matches('input,select,textarea'))load()},5000);
