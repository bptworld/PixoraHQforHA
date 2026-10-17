"""Local display studio: saved decks, downloaded cards, graphics and LAN playback."""
import asyncio,base64,hashlib,hmac,io,json,logging,os,shutil,sys,time,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp import web,ClientTimeout
from PIL import Image,ImageOps,ImageSequence
from card_store import CardStore
from pipeline import Pipeline,normalize_image

class CardSkipped(ValueError):pass
from client import PriorityMessageActive

class Studio:
    def __init__(self,app,root,selected,displays):
        self.app,self.root,self.selected,self.displays=app,root,selected,displays
        self.file=root/'studio.json';self.lock=asyncio.Lock();self.io_lock=asyncio.Lock();self.jobs={};self.runtime={};self.cache={};self.refresh_jobs={};self.renderer_revision=hashlib.sha256(Path(__file__).with_name('card_worker.py').read_bytes()).hexdigest()
        self.data=json.loads(self.file.read_text(encoding='utf-8')) if self.file.exists() else {'decks':{},'devices':{},'groups':{},'graphics':{},'settings':{'timezone':os.environ.get('TZ','UTC'),'timeFormat':'12','temperatureUnits':'F'}}
        self.store=CardStore(app['session'],root/'downloaded-cards')
        self.pipeline=Pipeline(root,self);self.monitors={};self.monitor_errors={};self.card_timing={};self.artwork_timing={};self.skipped={}
        self.runtime={ident:{'playing':False,'error':cfg['last_error']} for ident,cfg in self.data['devices'].items() if cfg.get('last_error')}

    def persist(self,body=None):
        self.root.mkdir(parents=True,exist_ok=True);temp=self.file.with_suffix('.tmp')
        temp.write_text(body if body is not None else json.dumps(self.data),encoding='utf-8');os.chmod(temp,0o600);os.replace(temp,self.file)

    async def save(self):
        async with self.io_lock:
            body=json.dumps(self.data)
            await asyncio.to_thread(self.persist,body)

    def used(self,data=None):
        data=self.data if data is None else data
        return {row['card'] for deck in data['decks'].values() for row in deck['items'] if 'card' in row}

    def public(self):
        result=json.loads(json.dumps(self.data))
        for deck in result['decks'].values():
            for item in deck['items']:
                for option in self.store.cards.get(item.get('card'),{}).get('options',[]):
                    if option.get('type')=='password' and option['key'] in item.get('options',{}):item['options'][option['key']]=''
        for key in list(result['settings']):
            if any(word in key.lower() for word in ('key','token','secret','password')):result['settings'][key]=''
        result['runtime']=json.loads(json.dumps(self.runtime))
        for ident,message in getattr(self,'monitor_errors',{}).items():result['runtime'].setdefault(ident,{})['warning']=message
        result['priority']={ident:{'queued':len(queue),'active':ident in self.pipeline.jobs and not self.pipeline.jobs[ident].done(),'error':self.pipeline.errors.get(ident,'')} for ident,queue in self.pipeline.data['queues'].items()}
        result['cards']=[{k:v for k,v in card.items() if k not in ('files','module')}|{'installed':self.store.installed(card['id'])} for card in self.store.cards.values()]
        result['displays']=sorted([{k:v for k,v in d.items() if k!='key'} for d in self.displays()],key=lambda d:d['name'].casefold())
        return result

    async def stop(self,ident,remember=True):
        monitor=getattr(self,'monitors',{}).pop(ident,None)
        if monitor:monitor.cancel();await asyncio.gather(monitor,return_exceptions=True)
        task=self.jobs.pop(ident,None)
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        self.runtime[ident]={'playing':False}
        if hasattr(self,'pipeline'):
            async with self.pipeline.lock:
                queue=self.pipeline.data['queues'].get(ident,[])
                remaining=[entry for entry in queue if entry.get('source')!='event']
                if len(remaining)!=len(queue):
                    self.pipeline.data['queues'][ident]=remaining;await self.pipeline.commit()
        if remember and ident in self.data['devices']:
            self.data['devices'][ident]['playing']=False
            await self.save()

    async def shutdown(self):
        for ident in list(self.jobs):await self.stop(ident,remember=False)
        tasks=list(self.refresh_jobs.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.refresh_jobs.clear()
        if hasattr(self,"pipeline"):await self.pipeline.close()

    def validate_deck(self,payload,previous=None):
        name=payload.get('name');items=payload.get('items')
        if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('Enter a deck name up to 80 characters.')
        if not isinstance(items,list) or len(items)>100:raise ValueError('A deck supports up to 100 cards.')
        result=[]
        previous={i['id']:i for i in (previous or {}).get('items',[])}
        for row in items:
            if not isinstance(row,dict):raise ValueError('Invalid deck item.')
            ident=row.get('id') or uuid.uuid4().hex
            if not isinstance(ident,str) or len(ident)>80 or any(i['id']==ident for i in result):raise ValueError('Invalid or duplicate deck item.')
            duration=row.get('duration',15)
            if type(duration)is not int or not 1<=duration<=300:raise ValueError('Choose 1 to 300 seconds per card.')
            item={'id':ident,'duration':duration,'enabled':row.get('enabled',True) is True}
            if row.get('card') in self.store.cards:
                item['card']=row['card'];options=row.get('options',{})
                if not isinstance(options,dict):raise ValueError('Invalid card options.')
                item['options']={}
                for option in self.store.cards[row['card']].get('options',[]):
                    key=option['key'];value=options.get(key,option.get('default',''))
                    if option.get('type')=='password' and not value:value=previous.get(ident,{}).get('options',{}).get(key,'')
                    if not isinstance(value,(str,int,float,bool)) or len(str(value))>4096:raise ValueError('Invalid card option.')
                    item['options'][key]=value
            elif row.get('graphic') in self.data['graphics']:item['graphic']=row['graphic']
            else:raise ValueError('Choose an available card or uploaded graphic.')
            result.append(item)
        return {'name':name.strip(),'items':result}

    async def mutate(self,operation):
        """Download before publishing a saved deck; serialize writes and collect committed references."""
        async with self.lock:
            current=self.data
            candidate=json.loads(json.dumps(current))
            self.data=candidate
            try:operation()
            finally:self.data=current
            try:
                await self.store.ensure(self.used(candidate))
                # Preserve a playback pause/failure that occurred while downloads were in progress.
                for ident,cfg in candidate['devices'].items():
                    if ident in current['devices']:cfg['playing']=current['devices'][ident].get('playing',False)
                self.data=candidate
                await self.save()
            except BaseException:
                self.data=current
                await self.store.collect(self.used())
                raise
            self.cache.clear();self.skipped.clear();self.artwork_timing.clear()
            # Saved-deck edits remove cached artwork for removed or changed cards too.
            tasks=list(self.refresh_jobs.values())
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            self.refresh_jobs.clear()
            await asyncio.to_thread(shutil.rmtree,self.root/'render-cache',True)
            await self.store.collect(self.used())

    async def ha(self,path):
        token=os.environ.get('SUPERVISOR_TOKEN')
        if not token:raise ValueError('Home Assistant API is unavailable. Restart the Pixora LED Studio app after updating it.')
        async with self.app['session'].get('http://supervisor/core/api/'+path,headers={'Authorization':'Bearer '+token},allow_redirects=False,timeout=ClientTimeout(total=10)) as response:
            if response.status!=200:raise ValueError('Could not read Home Assistant. Check the entity or HA connection.')
            return await response.json()

    async def render(self,item,width,device_id="preview",request_only=False,events=False):
        if 'graphic' in item:return (self.root/'graphics'/item['graphic']).read_bytes()
        card=self.store.cards[item['card']]
        options=dict(item.get('options',{}));options['_target']='matrixportal-s3-'+str(width)+'x32'
        request={'root':str(self.store.root.resolve()),'module':card['module'],'width':width,'options':options,'settings':self.data['settings'],'revision':self.store.catalog['commit'],'renderer':self.renderer_revision,'identity_options':item.get('options',{}),'card_id':card['id'],'protocol':2,'device_id':device_id,'dwell':item.get('duration',15),'events':events}
        if card['id']=='home_assistant_entity':
            entity=options.get('entityId','')
            if not isinstance(entity,str) or not all(c.isalnum() or c in '._' for c in entity):raise ValueError('Choose a Home Assistant entity.')
            request['ha_state']=await self.ha('states/'+entity)
        if request_only:return request
        encoded=json.dumps(request).encode()
        if len(encoded)>65536:raise ValueError('Card options are too large. Shorten the text values.')
        key=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        if getattr(self,'skipped',{}).get(key,0)>time.time():raise CardSkipped('No active artwork for this card.')
        cached=self.cache.get(key)
        ttl=1 if card['category'] in ('Fun',) or card['id'].startswith('clock') else 60
        if cached is None:
            cached=await asyncio.to_thread(self.read_artwork,key)
            if cached:
                if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=cached
                duration=getattr(self,'artwork_timing',{}).get(key)
                if duration:self.card_timing[(request['device_id'],request['module'])]=duration
        if cached:
            if time.time()-cached[0]>=ttl and key not in self.refresh_jobs:
                self.start_refresh(key,request)
            return cached[1]
        task=self.refresh_jobs.get(key)
        if task is None:task=self.start_refresh(key,request)
        return await asyncio.shield(task)

    def start_refresh(self,key,request):
        task=asyncio.create_task(self.refresh_artwork(key,request));self.refresh_jobs[key]=task
        def finished(completed):
            if self.refresh_jobs.get(key) is completed:self.refresh_jobs.pop(key,None)
            if not completed.cancelled() and completed.exception() and not isinstance(completed.exception(),CardSkipped):
                logging.warning('Local card artwork refresh failed; retaining any last good artwork.')
        task.add_done_callback(finished)
        return task

    def read_artwork(self,key):
        path=self.root/'render-cache'/(key+'.image')
        try:
            skip=path.with_suffix('.skip')
            if skip.is_file() and json.loads(skip.read_text()).get('expires',0)>time.time():raise CardSkipped('No active artwork for this card.')
            if path.stat().st_size>5*1024*1024:return None
            body=path.read_bytes()
            meta=path.with_suffix('.json')
            if meta.is_file():
                timing=json.loads(meta.read_text());duration=timing.get('duration')
                if type(duration)is int and 1<=duration<=300:
                    if not hasattr(self,'artwork_timing'):self.artwork_timing={}
                    self.artwork_timing[key]=duration
            with Image.open(io.BytesIO(body)) as image:image.verify()
            return path.stat().st_mtime,body
        except CardSkipped:raise
        except (OSError,ValueError):return None

    def write_artwork(self,key,body,duration=None):
        folder=self.root/'render-cache';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(key+'.image');temp=path.with_suffix('.tmp')
        temp.write_bytes(body);os.chmod(temp,0o600);os.replace(temp,path)
        path.with_suffix('.skip').unlink(missing_ok=True)
        if duration:
            meta=path.with_suffix('.json');staged=meta.with_suffix('.tmp')
            staged.write_text(json.dumps({'duration':duration}));os.chmod(staged,0o600);os.replace(staged,meta)
        for old in sorted(folder.glob('*.image'),key=lambda p:p.stat().st_mtime,reverse=True)[32:]:
            old.unlink(missing_ok=True);old.with_suffix('.json').unlink(missing_ok=True)

    def write_skip(self,key,expires):
        folder=self.root/'render-cache';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(key+'.skip');temp=path.with_suffix('.tmp')
        temp.write_text(json.dumps({'expires':expires}));os.chmod(temp,0o600);os.replace(temp,path)
        path.with_suffix('.image').unlink(missing_ok=True);path.with_suffix('.json').unlink(missing_ok=True)
        for old in sorted(folder.glob('*.skip'),key=lambda p:p.stat().st_mtime,reverse=True)[32:]:old.unlink(missing_ok=True)

    async def refresh_artwork(self,key,request):
        try:out=await self.render_request(request)
        except CardSkipped:
            self.cache.pop(key,None)
            if not hasattr(self,'skipped'):self.skipped={}
            if len(self.skipped)>=32:self.skipped.pop(next(iter(self.skipped)))
            expires=time.time()+15;self.skipped[key]=expires
            writing=asyncio.create_task(asyncio.to_thread(self.write_skip,key,expires))
            try:await asyncio.shield(writing)
            except asyncio.CancelledError:
                await asyncio.gather(writing,return_exceptions=True);raise
            except OSError:logging.warning('Could not save the inactive-card cache.')
            raise
        duration=self.card_timing.get((request['device_id'],request['module']))
        writing=asyncio.create_task(asyncio.to_thread(self.write_artwork,key,out,duration))
        try:await asyncio.shield(writing)
        except asyncio.CancelledError:
            # Let an in-flight atomic disk write finish before cleanup removes its folder.
            await asyncio.gather(writing,return_exceptions=True)
            raise
        except OSError:logging.warning("Could not save local artwork cache; using rendered artwork in memory.")
        if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
        self.cache[key]=(time.time(),out)
        return out

    async def render_request(self,request):
        await self.store.ensure({request['card_id']})
        env={k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','TZ','PYTHONIOENCODING')}
        async with self.store.lock:
            process=await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).with_name('card_worker.py')),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
            try:
                out,_=await asyncio.wait_for(process.communicate(json.dumps(request).encode()),30)
                if process.returncode or not out or len(out)>15*1024*1024:raise ValueError('This card could not render. Check its options and data-provider connection.')
            finally:
                if process.returncode is None:process.kill();await process.wait()
        result=json.loads(out)
        if request.get('events'):
            await self.accept_event(request,result)
        if result.get('skip'):raise CardSkipped('No active artwork for this card.')
        body=base64.b64decode(result['body'],validate=True)
        if len(body)>5*1024*1024:raise ValueError('Card artwork exceeds the hub limit.')
        self.card_timing[(request['device_id'],request['module'])]=result.get('duration',request['dwell'])
        return body

    async def accept_event(self,request,result):
        key=request['state_key'];event=result.get('event');entries=[]
        if event and self.data['devices'].get(request['device_id'],{}).get('playing'):
            event_id=hashlib.sha256((key+json.dumps(request.get('event_state',{}),sort_keys=True)+json.dumps(result.get('state',{}),sort_keys=True)+event['body']).encode()).hexdigest()
            group=request.get('wall_members',[]) if event.get('wall') else []
            if group:
                owners=[]
                for member,_ in group:
                    cfg=self.data['devices'].get(member,{})
                    if cfg.get('playing') and not self.quiet(cfg) and any(row.get('enabled') and row.get('card')==request['card_id'] and row.get('options',{})==request.get('identity_options',{}) for row in self.data['decks'].get(cfg.get('deck'),{}).get('items',[])):
                        owners.append(member)
                if owners and request['device_id']!=owners[0]:
                    await self.pipeline.submit([],key,result.get('state',{}));return
                def shared_state(value):
                    if isinstance(value,dict):
                        if '@datetime' in value:return None
                        return {k:shared_state(v) for k,v in value.items()}
                    if isinstance(value,list):return [shared_state(v) for v in value]
                    if isinstance(value,str):
                        for member,_ in group:
                            value=value.replace(':'+member+':',':group:')
                            if value.startswith(member+':'):value='group:'+value[len(member)+1:]
                    return value
                signature=json.dumps(shared_state(result.get('state',{})),sort_keys=True)
                event_id=hashlib.sha256((json.dumps(group)+request['module']+signature+event['body']).encode()).hexdigest()
                body=base64.b64decode(event['body']);offset=0;start=time.time()+2
                for ident,width in group:
                    sliced=self.slice_artwork(body,offset,width);offset+=width
                    entries.append((ident,{**event,'body':base64.b64encode(sliced).decode(),'event_id':event_id,'source':'event','start_at':start}))
            else:entries.append((request['device_id'],{**event,'event_id':event_id,'source':'event'}))
        await self.pipeline.submit(entries,key,result.get('state',{}))

    def slice_artwork(self,body,left,width):
        with Image.open(io.BytesIO(body)) as image:
            frames=[];timing=[]
            for frame in ImageSequence.Iterator(image):
                frames.append(frame.convert('RGB').crop((left,0,left+width,32)))
                timing.append(max(20,int(frame.info.get('duration',100))))
            out=io.BytesIO()
            if len(frames)>1:frames[0].save(out,'WEBP',save_all=True,append_images=frames[1:],duration=timing,loop=1,lossless=True,method=0)
            else:frames[0].save(out,'PNG')
            return out.getvalue()

    async def monitor(self,ident):
        try:
            while self.data['devices'].get(ident,{}).get('playing'):
                cfg=self.data['devices'][ident]
                if not self.quiet(cfg):
                    for item in self.data['decks'].get(cfg.get('deck'),{}).get('items',[]):
                        if not item.get('enabled') or 'card' not in item:continue
                        card=self.store.cards[item['card']]
                        # Event producers are discovered from downloaded source, not private Cloud code.
                        path=self.store.path('addons/'+card['module']+'.py')
                        source=await asyncio.to_thread(path.read_text,encoding='utf-8-sig')
                        if not any(token in source for token in ('_is_prefetch','deviceGraphic','wallGraphic','_priority','_group_wall')):continue
                        try:
                            info=await self.selected(ident).info()
                            request=await self.render(item,info['width'],device_id=ident,request_only=True,events=True)
                            state_key=hashlib.sha256(json.dumps({'device':ident,'item':item,'revision':self.store.catalog['commit']},sort_keys=True).encode()).hexdigest()
                            request['state_key']=state_key;request['event_state']=self.pipeline.data['states'].get(state_key,{})
                            for group in self.data['groups'].values():
                                if ident in group['members']:
                                    members=[(m,next(d['width'] for d in self.displays() if d['id']==m)) for m in group['members']]
                                    request['wall_members']=members;request['wall_width']=sum(w for _,w in members);request['wall_leader']=members[0][0];break
                            try:await self.render_request(request)
                            except CardSkipped:pass
                            self.monitor_errors.pop(ident,None)
                        except asyncio.CancelledError:raise
                        except Exception:self.monitor_errors[ident]='A card event check failed; regular deck playback continues.'
                await asyncio.sleep(15)
        except asyncio.CancelledError:raise
        except Exception:self.monitor_errors[ident]='Event monitoring stopped. Check the deck, then press Play.'

    async def queue_message(self,ident,message,color,duration):
        self.selected(ident)
        if type(duration)is not int or not 1<=duration<=300:raise ValueError('Choose 1 to 300 seconds.')
        if not isinstance(message,str) or not 1<=len(message)<=160 or any(ord(c)>126 or ord(c)<32 and c!='\n' for c in message):raise ValueError('Use 1 to 160 plain-text characters.')
        if not isinstance(color,(list,tuple)) or len(color)!=3 or any(type(c)is not int or not 0<=c<=255 for c in color):raise ValueError('Choose a valid RGB color.')
        await self.pipeline.submit([(ident,{'message':message,'color':list(color),'duration':duration,'source':'ha'})])

    async def queue_image(self,ident,body,duration):
        if type(duration)is not int or not 1<=duration<=300:raise ValueError('Choose 1 to 300 seconds.')
        info=await self.selected(ident).info()
        artwork=await asyncio.to_thread(normalize_image,body,info['width'])
        await self.pipeline.submit([(ident,{'body':base64.b64encode(artwork).decode(),'duration':duration,'source':'ha','once':False})])

    async def send_frame(self,client,body,width,duration,owner='deck',ident=None):
        with Image.open(io.BytesIO(body)) as image:
            image=ImageOps.pad(ImageOps.exif_transpose(image).convert('RGB'),(width,32),color='black')
            payload={'rgb':base64.b64encode(image.tobytes()).decode(),'width':width,'height':32,'duration':duration,'owner':owner}
        async def write():
            if ident and owner=='deck' and self.pipeline.signals(ident)[0].is_set():raise PriorityMessageActive('A local priority graphic is ready.')
            return await client.request('/api/frame',payload)
        if ident:await self.pipeline.write(ident,write)
        else:await write()

    async def deliver(self,client,body,width,duration,owner='deck',ident=None,once=False,wire_ident=None):
        with Image.open(io.BytesIO(body)) as image:
            frames=[]
            for index,frame in enumerate(ImageSequence.Iterator(image)):
                if index>=240:raise ValueError('Animation exceeds 240 frames.')
                out=io.BytesIO();frame.convert('RGB').save(out,'PNG')
                frames.append((out.getvalue(),max(.02,min(60,frame.info.get('duration',100)/1000))))
        remaining=float(duration);position=0
        while remaining>0:
            if ident:await self.pipeline.wait_ready(ident)
            pixels,delay=frames[min(position,len(frames)-1) if once else position%len(frames)]
            final=once and position>=len(frames)-1
            step=min(remaining,240 if len(frames)==1 or final else delay)
            lease=min(300,max(1,__import__('math').ceil(remaining+(60 if owner=='deck' else 0))))
            started=time.monotonic()
            try:await self.send_frame(client,pixels,width,lease,owner=owner,ident=ident or wire_ident)
            except PriorityMessageActive:
                if not ident:raise
                info=await client.info()
                await asyncio.sleep(min(.1,max(.02,float(info.get('remaining',1)))))
                continue
            elapsed=time.monotonic()-started
            wait=max(0,step-elapsed)
            left=await self.pipeline.delay(ident,wait) if ident else 0
            if not ident:await asyncio.sleep(wait)
            played=max(0,step-left);remaining-=max(played,elapsed)
            if left>0:continue
            position+=1

    def quiet(self,config):
        if not config.get('quiet'):return False
        current=datetime.now(ZoneInfo(self.data['settings'].get('timezone','UTC'))).strftime('%H:%M')
        start,end=config.get('quietStart','22:00'),config.get('quietEnd','06:00')
        return start<=current<end if start<end else current>=start or current<end

    async def play(self,ident):
        await self.stop(ident,remember=False)
        cfg=self.data['devices'].get(ident,{})
        if cfg.get('deck') not in self.data['decks']:raise ValueError('Choose and save a deck for this display first.')
        if not any(i['enabled'] for i in self.data['decks'][cfg['deck']]['items']):raise ValueError('Add at least one enabled card.')
        client=self.selected(ident);info=await client.info()
        if not info.get('localDecks'):raise ValueError('Update this panel to firmware 2.0.19 or newer before starting local decks.')
        self.data['devices'][ident].pop('last_error',None)
        self.data['devices'][ident]['playing']=True
        await self.save()
        async with self.pipeline.lock:
            self.pipeline.errors.pop(ident,None);self.pipeline.blocked.discard(ident);await self.pipeline.commit()
        self.jobs[ident]=asyncio.create_task(self.player(ident))
        self.monitors[ident]=asyncio.create_task(self.monitor(ident))

    async def player(self,ident):
        position=0;last_brightness=None;prepared=None;prepare_key=None;failed={};inactive=set();writing=False
        try:
            while True:
                cfg=self.data['devices'].get(ident,{})
                deck=self.data['decks'].get(cfg.get('deck'),{})
                items=[i for i in deck.get('items',[]) if i['enabled']]
                if not items:raise ValueError('Deck has no enabled cards.')
                if all(i['id'] in failed for i in items):raise ValueError('No playable cards remain. Skipped: '+', '.join(failed.values())+'. Fix the cards, then press Play.')
                if all(i['id'] in failed or i['id'] in inactive for i in items):
                    self.runtime[ident]={'playing':True,'status':'No active cards; checking again shortly'}
                    await asyncio.sleep(15);inactive.clear();continue
                if hasattr(self,'pipeline'):await self.pipeline.wait_ready(ident)
                client=self.selected(ident);info=await client.info()
                brightness=cfg.get('quietBrightness',0) if self.quiet(cfg) else cfg.get('brightness',60)
                if brightness!=last_brightness:
                    writing=True
                    await client.request('/api/settings',{'brightness':brightness});last_brightness=brightness
                    writing=False
                if info.get('active') and info.get('owner')!='deck':
                    self.runtime[ident]={'playing':True,'status':'HA message has priority'}
                    await asyncio.sleep(min(.25,max(.02,info.get('remaining',1))))
                    continue
                if self.quiet(cfg) and brightness==0:
                    self.runtime[ident]={'playing':True,'status':'Quiet hours'}
                    await asyncio.sleep(10);continue
                item=items[position%len(items)];position+=1
                if item['id'] in failed or item['id'] in inactive:continue
                name=self.store.cards[item['card']]['name'] if 'card' in item else self.data['graphics'].get(item.get('graphic'),{}).get('name','Graphic')
                key=(item['id'],info['width'])
                try:
                    if prepared is not None and prepare_key==key:
                        pending=prepared;prepared=None
                        body=await pending
                    else:
                        if prepared is not None:
                            prepared.cancel();await asyncio.gather(prepared,return_exceptions=True);prepared=None
                        body=await self.render(item,info['width'],device_id=ident)
                    # Artwork errors are isolated before any physical display write.
                    with Image.open(io.BytesIO(body)) as artwork:artwork.verify()
                except CardSkipped:
                    inactive.add(item['id']);continue
                except asyncio.CancelledError:raise
                except Exception:
                    failed[item['id']]=name
                    self.runtime[ident]={'playing':True,'status':'Skipping '+name,
                        'warning':'Skipped broken cards: '+', '.join(failed.values())+'. Fix them, then press Play to try them again.'}
                    continue
                # Re-read after potentially slow provider rendering: never overwrite a new HA message.
                current=await client.info()
                if current.get('active') and current.get('owner')!='deck':position-=1;continue
                name=self.store.cards[item['card']]['name'] if 'card' in item else self.data['graphics'][item['graphic']]['name']
                self.runtime[ident]={'playing':True,'status':name,'item':item['id'],**({'warning':'Skipped broken cards: '+', '.join(failed.values())+'. Fix them, then press Play to try them again.'} if failed else {})}
                next_item=next(items[(position+offset)%len(items)] for offset in range(len(items)) if items[(position+offset)%len(items)]['id'] not in failed and items[(position+offset)%len(items)]['id'] not in inactive)
                prepare_key=(next_item['id'],info['width'])
                prepared=asyncio.create_task(self.render(next_item,info['width'],device_id=ident))
                try:
                    writing=True
                    await self.deliver(client,body,info['width'],self.card_timing.get((ident,self.store.cards.get(item.get('card'),{}).get('module')),item['duration']),ident=ident)
                    writing=False
                except PriorityMessageActive:
                    writing=False
                    position-=1
                    await asyncio.sleep(1)
                    continue

        except asyncio.CancelledError:raise
        except Exception as exc:
            # A failed or uncertain panel write pauses all delivery to this display.
            if writing and hasattr(self,'pipeline'):
                async with self.pipeline.lock:
                    self.pipeline.errors[ident]='Deck delivery could not be confirmed. It was not retried. Check the display, then press Play.'
                    await self.pipeline.commit()
            self.runtime[ident]={'playing':False,'error':str(exc) if isinstance(exc,ValueError) else 'Playback stopped. Check the card and display connection.'}
            self.data['devices'].get(ident,{})['playing']=False
            self.data['devices'].get(ident,{})['last_error']=self.runtime[ident]['error']
            await self.save()
        finally:
            if prepared is not None:
                prepared.cancel()
                await asyncio.gather(prepared,return_exceptions=True)

    def register(self):
        routes=self.app.router
        async def object_data(request):
            data=await request.json()
            if not isinstance(data,dict):raise ValueError('Use a valid form.')
            return data
        async def state(request):return web.json_response(self.public())
        async def deck_save(request):
            payload=await object_data(request);ident=payload.get('id') or uuid.uuid4().hex
            if not isinstance(ident,str) or len(ident)>80:raise ValueError('Invalid deck.')
            value=self.validate_deck(payload,self.data['decks'].get(ident) or self.data['decks'].get(payload.get('copyFrom')))
            if ident not in self.data['decks'] and len(self.data['decks'])>=100:raise ValueError('Up to 100 decks are supported.')
            for device,cfg in self.data['devices'].items():
                if cfg.get('deck')==ident:await self.stop(device)
            display=payload.get('display')
            if display:self.selected(display)
            def save_deck():
                self.data['decks'][ident]=value
                if display and not self.data['devices'].get(display,{}).get('deck'):
                    cfg=self.data['devices'].setdefault(display,{'brightness':60,'quiet':False,'quietStart':'22:00','quietEnd':'06:00','quietBrightness':0})
                    cfg.update({'deck':ident,'playing':False})
            await self.mutate(save_deck)
            return web.json_response({'id':ident,'state':self.public()})
        async def deck_delete(request):
            ident=request.match_info['ident']
            if ident not in self.data['decks']:raise ValueError('Deck not found.')
            if any(cfg.get('deck')==ident for cfg in self.data['devices'].values()):raise ValueError('Unassign this deck from displays before deleting it.')
            await self.mutate(lambda:self.data['decks'].pop(ident));return web.json_response(self.public())
        async def device_save(request):
            ident=request.match_info['ident'];self.selected(ident);data=await object_data(request)
            if data.get('deck') and data['deck'] not in self.data['decks']:raise ValueError('Choose a saved deck.')
            for key in ('brightness','quietBrightness'):
                if type(data.get(key)) is not int or not 0<=data[key]<=100:raise ValueError('Choose brightness from 0 to 100%.')
            import re
            for key in ('quietStart','quietEnd'):
                if not isinstance(data.get(key),str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',data[key]):raise ValueError('Choose valid quiet hours.')
            value={k:data[k] for k in ('deck','brightness','quietBrightness','quietStart','quietEnd')};value['quiet']=data.get('quiet') is True
            await self.stop(ident)
            await self.mutate(lambda:self.data['devices'].__setitem__(ident,value))
            info=await self.selected(ident).info()
            if info.get('localDecks'):await self.selected(ident).request('/api/settings',{'brightness':value['brightness']})
            return web.json_response(self.public())
        async def action(request):
            data=await object_data(request);ident=data.get('id');targets=self.data['groups'].get(ident,{}).get('members',[ident])
            if data.get('action') not in ('play','stop','reboot'):raise ValueError('Choose Play, Stop or Reboot.')
            for target in targets:
                self.selected(target)
                if data['action']=='play':await self.play(target)
                elif data['action']=='stop':await self.stop(target)
                else:
                    await self.stop(target);await self.selected(target).request('/api/reboot',{})
            return web.json_response(self.public())
        async def ha_action(request):
            data=await object_data(request);ident=data.get('id');client=self.selected(ident)
            if not hmac.compare_digest(request.headers.get('Authorization',''),'Bearer '+client.key):raise web.HTTPForbidden()
            action_name=data.get('action')
            if action_name=='play':
                name=data.get('deck','')
                if name:
                    matches=[key for key,value in self.data['decks'].items() if key==name or value['name']==name]
                    if len(matches)!=1:raise ValueError('Choose a unique saved deck name or ID.')
                    await self.mutate(lambda:self.data['devices'].setdefault(ident,{'brightness':60}).update({'deck':matches[0]}))
                await self.play(ident)
            elif action_name=='stop':await self.stop(ident)
            elif action_name=='message':await self.queue_message(ident,data.get('message'),data.get('color',[255,255,255]),data.get('duration',10))
            elif action_name=='image_file':await self.queue_image(ident,base64.b64decode(data.get('body',''),validate=True),data.get('duration',10))
            elif action_name=='image':
                info=await client.info();pixels=base64.b64decode(data.get('rgb',''),validate=True)
                if len(pixels)!=info['width']*32*3:raise ValueError('Invalid image pixels.')
                image=Image.frombytes('RGB',(info['width'],32),pixels);out=io.BytesIO();image.save(out,'PNG')
                await self.queue_image(ident,out.getvalue(),data.get('duration',10))
            else:raise ValueError('Choose a supported display action.')
            return web.json_response({'accepted':True})
        async def preview(request):
            deck=self.data['decks'].get(request.query.get('deck'),{});item=next((i for i in deck.get('items',[]) if i['id']==request.query.get('item')),None)
            if item is None:raise ValueError('Save this card in a deck first.')
            width=int(request.query.get('width','64'))
            if width not in (64,128):raise ValueError('Choose S3 64 or 128.')
            body=await self.render(item,width)
            return web.Response(body=body,content_type='image/png' if body.startswith(b'\x89PNG') else 'image/webp',headers={'Cache-Control':'no-store'})
        async def entities(request):
            states=await self.ha('states')
            return web.json_response([{'id':s['entity_id'],'name':s.get('attributes',{}).get('friendly_name',s['entity_id']),'state':s['state']} for s in states])
        async def settings(request):
            data=await object_data(request)
            if not isinstance(data.get('timezone'),str):raise ValueError('Choose a timezone.')
            try:ZoneInfo(data['timezone'])
            except Exception:raise ValueError('Choose a valid timezone such as America/New_York.')
            allowed={'timezone','defaultZipCode','timeFormat','temperatureUnits','distanceUnits','dateFormat','openWeatherApiKey'}
            updates={k:v for k,v in data.items() if k in allowed and isinstance(v,str) and len(v)<=256 and (v or 'key' not in k.lower())}
            updates['defaultTimezone']=data['timezone']
            await self.mutate(lambda:self.data['settings'].update(updates));return web.json_response(self.public())
        async def groups(request):
            data=await object_data(request);ident=data.get('id') or uuid.uuid4().hex
            members=data.get('members');name=data.get('name')
            if not isinstance(ident,str) or len(ident)>80 or not isinstance(name,str) or not 1<=len(name.strip())<=80 or not isinstance(members,list) or not members or len(members)>30:raise ValueError('Name a group and choose its displays.')
            for member in members:self.selected(member)
            await self.mutate(lambda:self.data['groups'].__setitem__(ident,{'name':name.strip(),'members':list(dict.fromkeys(members))}));return web.json_response(self.public())
        async def group_delete(request):
            await self.mutate(lambda:self.data['groups'].pop(request.match_info['ident'],None));return web.json_response(self.public())
        async def upload(request):
            body=await request.read()
            if not body or len(body)>5*1024*1024:raise ValueError('Choose an image smaller than 5 MB.')
            with Image.open(io.BytesIO(body)) as image:
                if image.width*image.height>16000000:raise ValueError('Choose an image with at most 16 million pixels.')
                width=128 if image.width>64 else 64
            body=await asyncio.to_thread(normalize_image,body,width)
            ident=hashlib.sha256(body).hexdigest()+('.webp' if body.startswith(b'RIFF') else '.png');folder=self.root/'graphics';folder.mkdir(parents=True,exist_ok=True)
            (folder/ident).write_bytes(body)
            name=request.query.get('name','My graphic')[:80]
            await self.mutate(lambda:self.data['graphics'].__setitem__(ident,{'name':name}));return web.json_response(self.public())
        async def graphic(request):
            ident=request.match_info['ident']
            if ident not in self.data['graphics']:raise ValueError('Graphic not found.')
            return web.FileResponse(self.root/'graphics'/ident)
        async def graphic_delete(request):
            ident=request.match_info['ident']
            if ident not in self.data['graphics']:raise ValueError('Graphic not found.')
            if any(i.get('graphic')==ident for d in self.data['decks'].values() for i in d['items']):raise ValueError('Remove this graphic from saved decks first.')
            await self.mutate(lambda:self.data['graphics'].pop(ident,None));(self.root/'graphics'/ident).unlink(missing_ok=True);return web.json_response(self.public())
        routes.add_get('/api/studio',state);routes.add_post('/api/studio/decks',deck_save);routes.add_delete('/api/studio/decks/{ident}',deck_delete)
        routes.add_post('/api/studio/ha-action',ha_action);routes.add_post('/api/studio/devices/{ident}',device_save);routes.add_post('/api/studio/action',action);routes.add_get('/api/studio/preview',preview)
        routes.add_get('/api/studio/entities',entities);routes.add_post('/api/studio/settings',settings)
        routes.add_post('/api/studio/groups',groups);routes.add_delete('/api/studio/groups/{ident}',group_delete)
        routes.add_post('/api/studio/graphics',upload);routes.add_get('/api/studio/graphics/{ident}',graphic);routes.add_delete('/api/studio/graphics/{ident}',graphic_delete)
