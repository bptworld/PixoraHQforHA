"""Local display studio: saved decks, downloaded cards, graphics and LAN playback."""
import asyncio,base64,hashlib,hmac,io,json,logging,os,shutil,sys,time,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp import web,ClientTimeout
from PIL import Image,ImageOps,ImageSequence
from card_store import CardStore
from special_graphics import tests_for
from pipeline import Pipeline,normalize_image,WALL_START_LEAD

class PanelFrame:
    __slots__=('rgb',)
    def __init__(self,rgb):self.rgb=rgb

class CardSkipped(ValueError):pass
from client import PriorityMessageActive,DisplayUnavailable,DisplayWriteUnconfirmed
import quiet_hours

class Studio:
    def __init__(self,app,root,selected,displays):
        self.app,self.root,self.selected,self.displays=app,root,selected,displays
        self.file=root/'studio.json';self.lock=asyncio.Lock();self.io_lock=asyncio.Lock();self.jobs={};self.runtime={};self.cache={};self.refresh_jobs={};self.renderer_revision=hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in ('card_worker.py','special_graphics.py','graphic_cache.py','standings.py','graphic_layout.py'))).hexdigest()
        self.data=json.loads(self.file.read_text(encoding='utf-8')) if self.file.exists() else {'decks':{},'devices':{},'groups':{},'graphics':{},'settings':{'timezone':os.environ.get('TZ','UTC'),'timeFormat':'12','temperatureUnits':'F'}}
        self.store=CardStore(app['session'],root/'downloaded-cards')
        self.pipeline=Pipeline(root,self);self.monitors={};self.monitor_errors={};self.card_timing={};self.artwork_timing={};self.skipped={}
        self.runtime={ident:{'playing':False,'error':cfg['last_error']} for ident,cfg in self.data['devices'].items() if cfg.get('last_error')}
        self.graphic_jobs={};self.graphic_prepared={};self.frame_prepared={};self.slice_prepared={}
        self.score_monitors={};self.recovery_jobs={};self.recovery_task=None;self.starting=set();self.restarting=set();self.play_generation={}

    async def recover_display(self,ident,info):
        cfg=self.data['devices'].get(ident)
        if not cfg or info.get('id')!=ident or ident in self.starting:return
        boot=info.get('bootId');previous=cfg.get('bootId')
        changed=bool(boot and previous and boot!=previous)
        error=self.pipeline.errors.get(ident,'')
        desired=cfg.get('resume_on_boot',cfg.get('playing',False))
        # A new boot ends the old deck lease. Never replay uncertain priority
        # messages, or clear their delivery errors as part of deck recovery.
        priority_error=error and not error.startswith('Deck delivery could not be confirmed.')
        running=ident in self.jobs and not self.jobs[ident].done()
        if desired and error.startswith('Deck delivery could not be confirmed.') and not running:
            cfg['playing']=True
            await self.recover_deck_delivery(ident,self.selected(ident),saved_error=True)
            if cfg.get('resume_on_boot',False) and cfg.get('playing'):await self.play(ident)
            return
        if desired and not priority_error and (changed or (cfg.get('playing') and not running and not error and ident not in self.pipeline.blocked and ident not in self.restarting)):
            if changed:
                await self.stop(ident,remember=False)
            await self.play(ident)
        elif boot and (not previous or not desired):
            cfg['bootId']=boot;await self.save()

    async def watch_display(self,ident):
        try:
            while ident in self.data['devices']:
                cfg=self.data['devices'][ident]
                if cfg.get('resume_on_boot',cfg.get('playing',False)):
                    try:await self.recover_display(ident,await self.selected(ident).info())
                    except asyncio.CancelledError:raise
                    except ValueError:
                        if ident not in self.jobs or self.jobs[ident].done():
                            self.runtime[ident]={'playing':False,'status':'Waiting for display to reconnect…'}
                await asyncio.sleep(1)
        except asyncio.CancelledError:raise

    async def recovery_loop(self):
        try:
            while True:
                if (self.root/'.cleanup-started').exists():return
                for ident in list(self.data['devices']):
                    if ident not in self.recovery_jobs or self.recovery_jobs[ident].done():
                        self.recovery_jobs[ident]=asyncio.create_task(self.watch_display(ident))
                await asyncio.sleep(1)
        except asyncio.CancelledError:raise

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
        result['cards']=[{k:v for k,v in card.items() if k not in ('files','module')}|{'installed':self.store.installed(card['id']),'specialTests':tests_for(card)} for card in self.store.cards.values()]
        result['cardLibraryRevision']=self.store.catalog['commit'][:8]
        result['cardLibraryUpdated']=getattr(self.store,'updated_at',None) or self.store.catalog.get('published_at')
        result['displays']=sorted([{k:v for k,v in d.items() if k!='key'} for d in self.displays()],key=lambda d:d['name'].casefold())
        return result

    async def stop(self,ident,remember=True):
        self.play_generation[ident]=self.play_generation.get(ident,0)+1
        score=getattr(self,'score_monitors',{}).pop(ident,None)
        if score:score.cancel();await asyncio.gather(score,return_exceptions=True)
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
            self.data['devices'][ident]['resume_on_boot']=False
            await self.save()

    async def shutdown(self):
        recovery=[task for task in [self.recovery_task,*self.recovery_jobs.values()] if task]
        for task in recovery:task.cancel()
        await asyncio.gather(*recovery,return_exceptions=True)
        for ident in list(self.jobs):await self.stop(ident,remember=False)
        tasks=list(self.refresh_jobs.values())+list(self.graphic_jobs.values())
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
                    if ident in current['devices']:
                        for key in ('playing','resume_on_boot','bootId'):
                            if key in current['devices'][ident]:cfg[key]=current['devices'][ident][key]
                self.data=candidate
                await self.save()
            except BaseException:
                self.data=current
                await self.store.collect(self.used())
                raise
            # A running player may be awaiting this render. Cancelling it would also
            # cancel playback, so let in-flight artwork finish before collecting files.
            tasks=list(self.refresh_jobs.values())
            await asyncio.gather(*(asyncio.shield(task) for task in tasks),return_exceptions=True)
            self.cache.clear();self.skipped.clear();self.artwork_timing.clear()
            await asyncio.to_thread(shutil.rmtree,self.root/'render-cache',True)
            await self.store.collect(self.used())

    async def ha(self,path):
        token=os.environ.get('SUPERVISOR_TOKEN')
        if not token:raise ValueError('Home Assistant API is unavailable. Restart the Pixora LED Studio app after updating it.')
        async with self.app['session'].get('http://supervisor/core/api/'+path,headers={'Authorization':'Bearer '+token},allow_redirects=False,timeout=ClientTimeout(total=10)) as response:
            if response.status!=200:raise ValueError('Could not read Home Assistant. Check the entity or HA connection.')
            return await response.json()

    def sports_key(self,item,width,device_id):
        card=self.store.cards.get(item.get('card'),{})
        return json.dumps([device_id,card.get('module'),width,item.get('options',{})],sort_keys=True)

    def is_live_score(self,item,width,device_id):
        return getattr(self,'live_sports',{}).get(self.sports_key(item,width,device_id),False)

    def score_signal(self,item,width,device_id):
        if not hasattr(self,'score_signals'):self.score_signals={}
        return self.score_signals.setdefault(self.sports_key(item,width,device_id),asyncio.Event())

    def record_live_score(self,request,value,checked_at=None):
        if not hasattr(self,'live_sports'):self.live_sports={}
        if not hasattr(self,'live_checked'):self.live_checked={}
        key=json.dumps([request.get('device_id'),request['module'],request['width'],request.get('identity_options',request['options'])],sort_keys=True)
        if len(self.live_sports)>=300:
            old=next(iter(self.live_sports));self.live_sports.pop(old);self.live_checked.pop(old,None)
        self.live_sports[key]=value is True
        self.live_checked[key]=time.time() if checked_at is None else checked_at

    async def render(self,item,width,device_id="preview",request_only=False,events=False,fresh=False,cached_only=False):
        if 'graphic' in item:return (self.root/'graphics'/item['graphic']).read_bytes()
        card=self.store.cards[item['card']]
        options=dict(item.get('options',{}));options['_target']='matrixportal-s3-'+str(width)+'x32'
        request={'root':str(self.store.root.resolve()),'module':card['module'],'width':width,'options':options,'settings':self.data['settings'],'revision':self.store.catalog['commit']+card.get('sourceHash',''),'renderer':self.renderer_revision,'identity_options':item.get('options',{}),'card_id':card['id'],'protocol':2,'device_id':device_id,'dwell':item.get('duration',15),'events':events,'graphic_cache':str(self.root/'render-cache'/'priority')}
        if card['id']=='home_assistant_entity':
            entity=options.get('entityId','')
            if not isinstance(entity,str) or not all(c.isalnum() or c in '._' for c in entity):raise ValueError('Choose a Home Assistant entity.')
            request['ha_state']=await self.ha('states/'+entity)
        if request_only:return request
        encoded=json.dumps(request).encode()
        if len(encoded)>65536:raise ValueError('Card options are too large. Shorten the text values.')
        # A new Pac-Man appearance needs a new scene, including prefetches.
        if card['id']=='pacman':return await self.render_request(request)
        key=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        if getattr(self,'skipped',{}).get(key,0)>time.time():raise CardSkipped('No active artwork for this card.')
        cached=self.cache.get(key)
        if cached is None:
            cached=await asyncio.to_thread(self.read_artwork,key)
            if cached:
                if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
                self.cache[key]=cached
                duration=getattr(self,'artwork_timing',{}).get(key)
                if duration:self.card_timing[(request['device_id'],request['module'])]=duration
                self.record_live_score(request,getattr(self,'artwork_live',{}).get(key,False),cached[0])
        live=self.is_live_score(item,width,device_id)
        ttl=15 if live else 1 if card['category'] in ('Fun',) or card['id'].startswith('clock') else 60
        background=getattr(self,'score_monitors',{}).get(device_id)
        if cached and (cached_only or (not fresh and card['category']=='Sports' and background and not background.done())):return cached[1]
        checked=getattr(self,'live_checked',{}).get(self.sports_key(item,width,device_id),0)
        if fresh or (cached and live and time.time()-cached[0]>=ttl and time.time()-checked>=15):
            task=self.refresh_jobs.get(key) or self.start_refresh(key,request)
            try:return await asyncio.shield(task)
            except asyncio.CancelledError:raise
            except CardSkipped:raise
            except Exception:
                if not cached or not live or fresh:raise
                self.live_checked[self.sports_key(item,width,device_id)]=time.time()
                self.runtime.setdefault(device_id,{})['warning']='Live score update delayed; keeping the last score and checking again shortly.'
                return cached[1]
        if cached:
            if not live and time.time()-cached[0]>=ttl and key not in self.refresh_jobs:
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
                if not hasattr(self,'artwork_live'):self.artwork_live={}
                self.artwork_live[key]=timing.get('live_sports') is True
                if type(duration)is int and 1<=duration<=300:
                    if not hasattr(self,'artwork_timing'):self.artwork_timing={}
                    self.artwork_timing[key]=duration
            with Image.open(io.BytesIO(body)) as image:image.verify()
            return path.stat().st_mtime,body
        except CardSkipped:raise
        except (OSError,ValueError):return None

    def write_artwork(self,key,body,duration=None,live=False):
        folder=self.root/'render-cache';folder.mkdir(parents=True,exist_ok=True)
        path=folder/(key+'.image');temp=path.with_suffix('.tmp')
        temp.write_bytes(body);os.chmod(temp,0o600);os.replace(temp,path)
        path.with_suffix('.skip').unlink(missing_ok=True)
        if duration:
            meta=path.with_suffix('.json');staged=meta.with_suffix('.tmp')
            staged.write_text(json.dumps({'duration':duration,'live_sports':live}));os.chmod(staged,0o600);os.replace(staged,meta)
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
        live=getattr(self,'live_sports',{}).get(json.dumps([request.get('device_id'),request['module'],request['width'],request.get('identity_options',request['options'])],sort_keys=True),False)
        writing=asyncio.create_task(asyncio.to_thread(self.write_artwork,key,out,duration,live))
        try:await asyncio.shield(writing)
        except asyncio.CancelledError:
            # Let an in-flight atomic disk write finish before cleanup removes its folder.
            await asyncio.gather(writing,return_exceptions=True)
            raise
        except OSError:logging.warning("Could not save local artwork cache; using rendered artwork in memory.")
        if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
        self.cache[key]=(time.time(),out)
        card=self.store.cards.get(request.get('card_id'),{})
        if card.get('category')=='Sports':
            self.score_signal({'card':request['card_id'],'options':request.get('identity_options',{})},request['width'],request['device_id']).set()
        return out

    async def run_worker(self,request):
        await self.store.ensure({request['card_id']})
        env={k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','TZ','PYTHONIOENCODING')}
        async with self.store.lock:
            process=await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).with_name('card_worker.py')),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
            try:
                out,_=await asyncio.wait_for(process.communicate(json.dumps(request).encode()),30)
                if process.returncode or not out or len(out)>15*1024*1024:raise ValueError('This card could not render. Check its options and data-provider connection.')
            finally:
                if process.returncode is None:process.kill();await process.wait()
        return json.loads(out)

    async def render_request(self,request):
        result=await self.run_worker(request)
        if not request.get('events'):self.record_live_score(request,result.get('live_sports',False))
        if request.get('events'):
            await self.accept_event(request,result)
        if result.get('skip'):raise CardSkipped('No active artwork for this card.')
        body=base64.b64decode(result['body'],validate=True)
        if len(body)>5*1024*1024:raise ValueError('Card artwork exceeds the hub limit.')
        self.card_timing[(request['device_id'],request['module'])]=result.get('duration',request['dwell'])
        return body

    async def accept_event(self,request,result):
        key=request['state_key'];event=result.get('event');entries=[]
        if not event:
            for graphic in result.get('warm_graphics',[])[:1]:
                try:
                    body=base64.b64decode(graphic['body'],validate=True)
                    if len(body)<=5*1024*1024:await self.prepared_slices(body,graphic['members'])
                except Exception:logging.debug('Could not prepare a warm wall scene; event rendering remains available.')
        if event and self.data['devices'].get(request['device_id'],{}).get('playing'):
            event_id=hashlib.sha256((key+json.dumps(request.get('event_state',{}),sort_keys=True)+json.dumps(result.get('state',{}),sort_keys=True)+event['body']).encode()).hexdigest()
            group=event.get('wall_members',request.get('wall_members',[])) if event.get('wall') else []
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
                body=base64.b64decode(event['body'])
                slices=await self.prepared_slices(body,group)
                for ident,width,sliced in slices:
                    entries.append((ident,{**event,'body':sliced,'event_id':event_id,'source':'event','start_at':0,'wall_members':[member for member,_ in group],'wall_width':width}))
                ready_at=time.time()+WALL_START_LEAD
                for _,payload in entries:payload['start_at']=ready_at
            else:entries.append((request['device_id'],{**event,'event_id':event_id,'source':'event'}))
        await self.pipeline.submit(entries,key,result.get('state',{}))

    async def prepared_frames(self,body,width):
        key=(hashlib.sha256(body).hexdigest(),width)
        if not hasattr(self,'frame_prepared'):self.frame_prepared={}
        if key in self.frame_prepared:return self.frame_prepared[key]
        def decode():
            frames=[];size=0
            with Image.open(io.BytesIO(body)) as image:
                for index,frame in enumerate(ImageSequence.Iterator(image)):
                    if index>=2048:raise ValueError('Animation exceeds 2048 frames.')
                    rgb=ImageOps.pad(ImageOps.exif_transpose(frame).convert('RGB'),(width,32),color='black')
                    pixels=base64.b64encode(rgb.tobytes()).decode();size+=len(pixels)
                    if size>32*1024*1024:raise ValueError('Decoded animation exceeds the hub limit.')
                    frames.append((PanelFrame(pixels),max(.02,min(60,frame.info.get('duration',100)/1000))))
            return frames,size
        frames,size=await asyncio.to_thread(decode)
        while self.frame_prepared and (len(self.frame_prepared)>=8 or size+sum(sum(len(frame.rgb) for frame,_ in value) for value in self.frame_prepared.values())>32*1024*1024):
            self.frame_prepared.pop(next(iter(self.frame_prepared)))
        self.frame_prepared[key]=frames
        return frames

    async def prepared_slices(self,body,widths):
        key=hashlib.sha256(body+json.dumps(widths).encode()).hexdigest()
        if not hasattr(self,'slice_prepared'):self.slice_prepared={}
        slices=self.slice_prepared.get(key)
        if slices is None:
            def crop():
                offset=0;result=[]
                for member,width in widths:
                    result.append((member,width,base64.b64encode(self.slice_artwork(body,offset,width)).decode()));offset+=width
                return result
            slices=await asyncio.to_thread(crop)
            size=sum(len(value) for _,_,value in slices)
            while self.slice_prepared and (len(self.slice_prepared)>=8 or size+sum(sum(len(value) for _,_,value in rows) for rows in self.slice_prepared.values())>16*1024*1024):
                self.slice_prepared.pop(next(iter(self.slice_prepared)))
            if size<=16*1024*1024:self.slice_prepared[key]=slices
        # Decode before queueing so every panel reaches the wall barrier ready to send.
        await asyncio.gather(*(self.prepared_frames(base64.b64decode(value),width) for _,width,value in slices))
        return slices

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

    async def score_monitor(self,ident):
        due={}
        try:
            while self.data['devices'].get(ident,{}).get('playing'):
                cfg=self.data['devices'][ident]
                if not self.quiet(cfg):
                    width=next((d['width'] for d in self.displays() if d['id']==ident),None)
                    if width is None:
                        await asyncio.sleep(1)
                        continue
                    for item in list(self.data['decks'].get(cfg.get('deck'),{}).get('items',[])):
                        card=self.store.cards.get(item.get('card'),{})
                        if not item.get('enabled') or card.get('category')!='Sports':continue
                        key=json.dumps([item,self.store.catalog['commit']],sort_keys=True)
                        now=time.monotonic()
                        if due.get(key,0)>now:continue
                        try:
                            await self.render(item,width,device_id=ident,fresh=True)
                            warning=self.runtime.get(ident,{}).get('warning','')
                            if warning.startswith('Sports background update delayed;'):self.runtime[ident].pop('warning',None)
                        except asyncio.CancelledError:raise
                        except CardSkipped:pass
                        except Exception:
                            self.runtime.setdefault(ident,{})['warning']='Sports background update delayed; keeping the last available artwork.'
                        interval=15 if self.is_live_score(item,width,ident) else 300 if 'standings' in card.get('id','') else 60
                        due[key]=max(time.monotonic(),now+interval)
                await asyncio.sleep(1)
        except asyncio.CancelledError:raise

    async def monitor(self,ident):
        next_checks={}
        try:
            while self.data['devices'].get(ident,{}).get('playing'):
                cfg=self.data['devices'][ident]
                if not self.quiet(cfg):
                    for item in self.data['decks'].get(cfg.get('deck'),{}).get('items',[]):
                        if not item.get('enabled') or 'card' not in item:continue
                        card=self.store.cards[item['card']]
                        if next_checks.get(item['id'],0)>time.monotonic():continue
                        next_checks[item['id']]=time.monotonic()+(1 if card['id']=='launch_countdown' else 15)
                        try:
                            # Event producers are discovered from downloaded source, not private Cloud code.
                            path=self.store.path('addons/'+card['module']+'.py')
                            source=await asyncio.to_thread(path.read_text,encoding='utf-8-sig')
                            if not (any(token in source for token in ('_is_prefetch','deviceGraphic','_device_graphic','wallGraphic','_priority','_group_wall','maybe_score_alert','game_moment_alert','final_win_alert')) or ('_no_replay' in source and '_STATE' in source)):continue
                            # Event rendering needs the confirmed panel width, not a
                            # new network status poll for every card event check.
                            width=next(d['width'] for d in self.displays() if d['id']==ident)
                            request=await self.render(item,width,device_id=ident,request_only=True,events=True)
                            state_key=hashlib.sha256(json.dumps({'device':ident,'item':{'id':item['id'],'card':item['card'],'options':item.get('options',{})},'revision':self.store.catalog['commit']},sort_keys=True).encode()).hexdigest()
                            request['state_key']=state_key;request['event_state']=self.pipeline.data['states'].get(state_key,{})
                            request['wall_groups']={gid:[(m,next(d['width'] for d in self.displays() if d['id']==m)) for m in g['members']] for gid,g in self.data['groups'].items() if ident in g['members']}
                            request['card_metadata']=card
                            for group in self.data['groups'].values():
                                if ident in group['members']:
                                    members=[(m,next(d['width'] for d in self.displays() if d['id']==m)) for m in group['members']]
                                    request['wall_members']=members;request['wall_width']=sum(w for _,w in members);request['wall_leader']=members[0][0];break
                            try:await self.render_request(request)
                            except CardSkipped:pass
                            self.monitor_errors.pop(ident,None)
                        except asyncio.CancelledError:raise
                        except Exception:self.monitor_errors[ident]='A card event check failed; special graphics may be delayed.'
                # Launch shake has a five-second trigger window; do not poll it every 15s.
                await asyncio.sleep(1)
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
        if isinstance(body,PanelFrame):rgb=body.rgb
        else:
            with Image.open(io.BytesIO(body)) as image:
                image=ImageOps.pad(ImageOps.exif_transpose(image).convert('RGB'),(width,32),color='black')
                rgb=base64.b64encode(image.tobytes()).decode()
        payload={'rgb':rgb,'width':width,'height':32,'duration':duration,'owner':owner}
        async def write():
            if ident and owner=='deck' and self.pipeline.signals(ident)[0].is_set():raise PriorityMessageActive('A local priority graphic is ready.')
            return await client.request('/api/frame',payload)
        if ident:await self.pipeline.write(ident,write)
        else:await write()

    async def recover_deck_delivery(self,ident,client,saved_error=False):
        """Resolve a lost response with reads; never resend the uncertain frame."""
        while self.data['devices'].get(ident,{}).get('playing'):
            self.runtime[ident]={'playing':True,'status':'Reconnecting · checking the last card…'}
            info=await self.playback_info(ident,client)
            if not self.data['devices'].get(ident,{}).get('playing'):raise asyncio.CancelledError
            if info.get('id')!=ident or type(info.get('active')) is not bool:
                raise ValueError('Could not verify the display playback state.')
            # Let a possibly accepted deck frame expire before advancing. Priority
            # messages keep their own queue/confirmation rules and are never replayed.
            if info['active'] and info.get('owner')=='deck':
                await asyncio.sleep(1)
                continue
            async with self.pipeline.lock:
                error=self.pipeline.errors.get(ident,'')
                if error:
                    if not saved_error or not error.startswith('Deck delivery could not be confirmed.'):raise ValueError(error)
                    self.pipeline.errors.pop(ident,None)
                    await self.pipeline.commit()
                self.pipeline.blocked.discard(ident)
            self.runtime[ident]={'playing':True,'status':'Connection restored · continuing to the next card…'}
            return
        raise asyncio.CancelledError

    async def deliver(self,client,body,width,duration,owner='deck',ident=None,once=False,wire_ident=None,synchronize=None,group_check=None,refresh_signal=None):
        frames=await self.prepared_frames(body,width)
        if synchronize:
            # All wall slices are decoded before the barrier releases any panel.
            start=await synchronize()
            await self.deliver_timeline(client,frames,width,float(duration),start,owner,wire_ident,once,group_check)
            return
        remaining=float(duration);position=0
        while remaining>0:
            if ident:
                if self.pipeline.signals(ident)[0].is_set():raise PriorityMessageActive('An interrupt is ready.')
                await self.pipeline.wait_ready(ident)
            pixels,delay=frames[min(position,len(frames)-1) if once else position%len(frames)]
            final=once and position>=len(frames)-1
            step=min(remaining,240 if len(frames)==1 or final else delay)
            lease=min(300,max(1,__import__('math').ceil(remaining+(60 if owner=='deck' else 0))))
            started=time.monotonic()
            try:
                await self.send_frame(client,pixels,width,lease,owner=owner,ident=ident or wire_ident)
            except DisplayWriteUnconfirmed:
                if owner!='deck' or not ident:raise
                await self.recover_deck_delivery(ident,client)
                return False
            elapsed=time.monotonic()-started
            wait=max(0,step-elapsed)
            if refresh_signal is not None:
                pending=wait
                while pending>0:
                    if refresh_signal.is_set():return float(max(0,remaining-elapsed-(wait-pending)))
                    pause=min(1,pending)
                    left=await self.pipeline.delay(ident,pause) if ident else 0
                    if not ident:await asyncio.sleep(pause)
                    if left>0:raise PriorityMessageActive('An interrupt is ready.')
                    pending-=pause
                remaining-=max(step,elapsed);position+=1
                continue
            left=await self.pipeline.delay(ident,wait) if ident else 0
            if not ident:await asyncio.sleep(wait)
            played=max(0,step-left);remaining-=max(played,elapsed)
            if left>0:raise PriorityMessageActive('An interrupt is ready.')
            position+=1
        return True

    async def deliver_score(self,client,body,width,duration,item,ident):
        remaining=float(duration)
        sports=self.store.cards.get(item.get('card'),{}).get('category')=='Sports'
        while remaining>0:
            if self.quiet(self.data['devices'].get(ident,{})):return
            signal=self.score_signal(item,width,ident) if sports else None
            if sports:
                signal.clear()
                # The background poller owns provider requests. Showing a card
                # only reads its latest prepared artwork, including hidden polls.
                try:body=await self.render(item,width,device_id=ident,cached_only=True)
                except asyncio.CancelledError:raise
                except Exception:pass
            step=remaining
            delivered=await self.deliver(client,body,width,step,ident=ident,**({'refresh_signal':signal} if signal else {}))
            if delivered is False:return
            if type(delivered) is float:
                remaining=delivered;continue
            remaining-=step

    async def deliver_timeline(self,client,frames,width,duration,start,owner,wire_ident,once,check):
        import bisect,math
        ends=[];total=0
        for _,delay in frames:total+=delay;ends.append(total)
        await asyncio.sleep(max(0,start-time.monotonic()))
        while True:
            if check:check()
            elapsed=max(0,time.monotonic()-start)
            if elapsed>=duration:return
            phase=elapsed if once else elapsed%total
            index=min(len(frames)-1,bisect.bisect_right(ends,phase))
            # Skip expired frames after slow Wi-Fi writes; never stretch one slice's clock.
            boundary=duration if once and index==len(frames)-1 else elapsed-phase+ends[index]
            remaining=duration-elapsed
            await self.send_frame(client,frames[index][0],width,min(300,max(1,math.ceil(remaining))),owner=owner,ident=wire_ident)
            deadline=start+min(duration,boundary,elapsed+240)
            await asyncio.sleep(max(0,deadline-time.monotonic()))

    def quiet(self,config):
        return quiet_hours.active(config,quiet_hours.now(self.data.get('settings',{})))

    def quiet_remaining(self,config,duration):
        seconds=quiet_hours.boundary(config,quiet_hours.now(self.data.get('settings',{})))
        return min(duration,seconds) if seconds is not None else duration

    async def apply_brightness(self,ident,client,info,value):
        if not hasattr(self,'brightness_pending'):self.brightness_pending={}
        if ident in self.brightness_pending:
            # A fresh GET resolves a lost POST response. Never blindly repeat it.
            if type(info.get('brightness')) is not int:
                self.runtime[ident]={'playing':bool(self.data['devices'].get(ident,{}).get('playing')),'status':'Waiting to confirm display brightness…'}
                await asyncio.sleep(1);return False
            self.brightness_pending.pop(ident,None)
        if info.get('brightness')==value:return True
        try:await client.request('/api/settings',{'brightness':value})
        except DisplayWriteUnconfirmed:
            self.brightness_pending[ident]=value
            self.runtime[ident]={'playing':bool(self.data['devices'].get(ident,{}).get('playing')),'status':'Waiting to confirm display brightness…'}
            await asyncio.sleep(1);return False
        return True

    async def save_display_settings(self,ident,value):
        # Configuration saves preserve both running decks and explicit pauses.
        await self.mutate(lambda:self.data['devices'].setdefault(ident,{}).update(value))
        cfg=self.data['devices'][ident]
        brightness=cfg.get('quietBrightness',10) if self.quiet(cfg) else cfg.get('brightness',60)
        try:
            client=self.selected(ident);info=await client.info()
            if info.get('localDecks'):await self.apply_brightness(ident,client,info,brightness)
        except DisplayUnavailable:pass

    async def play(self,ident):
        if ident in self.starting:raise ValueError('Playback is already starting for this display.')
        self.starting.add(ident)
        try:await self._play(ident)
        finally:self.starting.discard(ident)

    async def _play(self,ident):
        await self.stop(ident,remember=False)
        generation=self.play_generation[ident]
        cfg=self.data['devices'].get(ident,{})
        if cfg.get('deck') not in self.data['decks']:raise ValueError('Choose and save a deck for this display first.')
        if not any(i['enabled'] for i in self.data['decks'][cfg['deck']]['items']):raise ValueError('Add at least one enabled card.')
        client=self.selected(ident);info=await client.info()
        if self.play_generation.get(ident)!=generation:return
        if not info.get('localDecks'):raise ValueError('Update this panel to firmware 2.0.19 or newer before starting local decks.')
        self.data['devices'][ident].pop('last_error',None)
        self.data['devices'][ident]['playing']=True
        self.data['devices'][ident]['resume_on_boot']=True
        self.restarting.discard(ident)
        if info.get('bootId'):self.data['devices'][ident]['bootId']=info['bootId']
        await self.save()
        async with self.pipeline.lock:
            self.pipeline.errors.pop(ident,None);self.pipeline.blocked.discard(ident);await self.pipeline.commit()
        if self.play_generation.get(ident)!=generation:return
        self.runtime[ident]={'playing':True,'status':'Preparing the first card…'}
        self.jobs[ident]=asyncio.create_task(self.player(ident))
        self.monitors[ident]=asyncio.create_task(self.monitor(ident))
        if not hasattr(self,'score_monitors'):self.score_monitors={}
        self.score_monitors[ident]=asyncio.create_task(self.score_monitor(ident))

    async def playback_info(self,ident,client):
        # These are read-only checks. A temporarily unavailable panel must not
        # turn a running deck into a permanently saved pause.
        while self.data['devices'].get(ident,{}).get('playing'):
            try:return await client.info()
            except DisplayUnavailable:
                self.runtime[ident]={'playing':True,'status':'Waiting for display to reconnect…'}
                await asyncio.sleep(1)
        raise asyncio.CancelledError

    async def player(self,ident):
        position=0;last_brightness=None;prepared=None;prepare_key=None;failed={};failed_until={};inactive={};writing=False;deck_snapshot=None
        try:
            while True:
                cfg=self.data['devices'].get(ident,{})
                if hasattr(self,'pipeline'):await self.pipeline.wait_ready(ident)
                client=self.selected(ident);info=await self.playback_info(ident,client)
                is_quiet=self.quiet(cfg)
                brightness=cfg.get('quietBrightness',10) if is_quiet else cfg.get('brightness',60)
                if brightness!=last_brightness or ('brightness' in info and info['brightness']!=brightness):
                    if not await self.apply_brightness(ident,client,info,brightness):continue
                    last_brightness=brightness
                if info.get('active') and info.get('owner')!='deck':
                    self.runtime[ident]={'playing':True,'status':'HA message has priority'}
                    await asyncio.sleep(min(.25,max(.02,info.get('remaining',1))));continue
                if is_quiet:
                    if prepared is not None:
                        prepared.cancel();await asyncio.gather(prepared,return_exceptions=True);prepared=None
                    current=quiet_hours.now(self.data.get('settings',{}))
                    body=quiet_hours.clock(info['width'],current,self.data['settings'],self.store.root/'assets')
                    self.runtime[ident]={'playing':True,'status':'Quiet hours · Off' if brightness==0 else 'Quiet hours · Clock'}
                    try:
                        writing=True
                        await self.deliver(client,body,info['width'],self.quiet_remaining(cfg,min(10,60-current.second)),ident=ident)
                        writing=False
                    except PriorityMessageActive:writing=False
                    continue
                deck=self.data['decks'].get(cfg.get('deck'),{})
                snapshot=json.dumps(deck,sort_keys=True)
                if snapshot!=deck_snapshot:
                    failed.clear();failed_until.clear();inactive.clear();deck_snapshot=snapshot
                # Empty live-data cards can gain content while other cards keep playing.
                inactive={key:retry_at for key,retry_at in inactive.items() if retry_at>time.monotonic()}
                for key in list(failed):
                    if failed_until.get(key,0)<=time.monotonic():failed.pop(key);failed_until.pop(key,None)
                items=[i for i in deck.get('items',[]) if i['enabled']]
                if not items:raise ValueError('Deck has no enabled cards.')
                if all(i['id'] in failed or i['id'] in inactive for i in items):
                    self.runtime[ident]={'playing':True,'status':'No active cards; checking again shortly',**({'warning':'Cards temporarily unavailable: '+', '.join(failed.values())+'. Retrying automatically.'} if failed else {})}
                    await asyncio.sleep(15);inactive.clear();continue
                item=items[position%len(items)];position+=1
                if item['id'] in failed or item['id'] in inactive:continue
                name=self.store.cards[item['card']]['name'] if 'card' in item else self.data['graphics'].get(item.get('graphic'),{}).get('name','Graphic')
                key=(json.dumps(item,sort_keys=True),info['width'])
                try:
                    if prepared is not None and prepare_key==key:
                        pending=prepared;prepared=None
                        body=await pending
                    else:
                        if prepared is not None:
                            prepared.cancel();await asyncio.gather(prepared,return_exceptions=True);prepared=None
                        body=await self.render(item,info['width'],device_id=ident)
                    # Prefetch may have happened earlier in a short deck rotation.
                    # Recheck live-score freshness before showing that snapshot.
                    if self.is_live_score(item,info['width'],ident):
                        body=await self.render(item,info['width'],device_id=ident)
                    # Artwork errors are isolated before any physical display write.
                    with Image.open(io.BytesIO(body)) as artwork:artwork.verify()
                except CardSkipped:
                    inactive[item['id']]=time.monotonic()+15;continue
                except asyncio.CancelledError:raise
                except Exception:
                    failed[item['id']]=name
                    failed_until[item['id']]=time.monotonic()+60
                    self.runtime[ident]={'playing':True,'status':'Skipping '+name,
                        'warning':'Cards temporarily unavailable: '+', '.join(failed.values())+'. Retrying automatically.'}
                    continue
                # Re-read after potentially slow provider rendering: never overwrite a new HA message.
                current=await self.playback_info(ident,client)
                if self.quiet(cfg):continue
                if current.get('active') and current.get('owner')!='deck':position-=1;continue
                name=self.store.cards[item['card']]['name'] if 'card' in item else self.data['graphics'][item['graphic']]['name']
                self.runtime[ident]={'playing':True,'status':name,'item':item['id'],**({'warning':'Cards temporarily unavailable: '+', '.join(failed.values())+'. Retrying automatically.'} if failed else {})}
                next_item=next(items[(position+offset)%len(items)] for offset in range(len(items)) if items[(position+offset)%len(items)]['id'] not in failed and items[(position+offset)%len(items)]['id'] not in inactive)
                prepare_key=(json.dumps(next_item,sort_keys=True),info['width'])
                prepared=asyncio.create_task(self.render(next_item,info['width'],device_id=ident))
                try:
                    writing=True
                    await self.deliver_score(client,body,info['width'],self.quiet_remaining(cfg,self.card_timing.get((ident,self.store.cards.get(item.get('card'),{}).get('module')),item['duration'])),item,ident)
                    writing=False
                except PriorityMessageActive:
                    writing=False
                    await self.pipeline.wait_ready(ident)
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

    async def standings_groups(self,payload):
        from standings import endpoint,choices,group_id,legacy_match
        card=self.store.cards.get(payload.get('card'))
        if not card or not card.get('standingsBrowser'):raise ValueError('Choose a standings card.')
        previous=self.data['decks'].get(payload.get('deck'))
        item=self.validate_deck({'name':'Standings groups','items':[{'id':payload.get('item') or 'groups','card':card['id'],'options':payload.get('options',{}),'duration':10}]},previous)['items'][0]
        options=item['options']
        if card['standingsBrowser']=='fantasy':
            if card['id']=='yahoo_fantasy_standings':
                if not options.get('leagueKey') or not options.get('accessToken'):raise ValueError('Enter your Yahoo league key and access token first.')
            elif not options.get('leagueId'):raise ValueError('Enter your fantasy league ID first.')
            request=await self.render(item,64,request_only=True)
            request['standings_groups']=True
            async with self.lock:
                try:return await self.run_worker(request)
                finally:await self.store.collect(self.used())
        url=endpoint(card,options)
        async def fetch(url):
            if not hasattr(self,'standings_cache'):self.standings_cache={}
            cached=self.standings_cache.get(url)
            if cached and time.monotonic()-cached[0]<3600:return cached[1]
            async with self.app['session'].get(url,allow_redirects=False,timeout=ClientTimeout(total=15)) as response:
                if response.status!=200:raise ValueError('The standings provider is unavailable. Try loading divisions again.')
                body=bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body)>5*1024*1024:raise ValueError('Standings response exceeds the hub limit.')
                data=json.loads(body)
            if len(self.standings_cache)>=80:self.standings_cache.pop(next(iter(self.standings_cache)))
            self.standings_cache[url]=(time.monotonic(),data)
            return data
        selected=str(payload.get('group') or '')
        selection=None
        if selected and selected!='auto':
            if selected.startswith('espn:'):ident=group_id(selected)
            else:
                root=await fetch(url);node=legacy_match(root.get('children',[]),selected)
                if node is None and selected.startswith(('al_','nl_')):
                    parent=legacy_match(root.get('children',[]),selected[:2])
                    if parent:
                        child=await fetch(url+'?group='+str(parent['id']))
                        node=legacy_match(child.get('children',[]),selected[3:])
                if node is None:raise ValueError('The saved standings group is unavailable. Choose another conference or division.')
                ident=str(node['id'])
            data=await fetch(url+'?group='+ident)
            if str(data.get('id'))!=ident:raise ValueError('This standings group is unavailable.')
            selection={'value':'espn:'+ident,'label':str(data.get('name') or ident)}
        else:data=await fetch(url)
        groups=choices(data,include_root=selection is None)
        return {'groups':groups,'selection':selection,'message':'' if groups else 'No further divisions are available from this provider.' if selection else 'No standings groups are available from this provider right now.'}

    def graphic_group(self,ident,target):
        if target.startswith('group:'):
            group=self.data['groups'].get(target[6:])
            if not group or ident not in group['members']:raise ValueError('Choose an available group containing this display.')
            return group
        groups=[g for g in self.data['groups'].values() if ident in g['members']]
        if len(groups)!=1:raise ValueError('Choose a specific display group for this special graphic.')
        return groups[0]

    async def test_graphic(self,payload,prepare=False):
        ident=payload.get('display');self.selected(ident)
        card=self.store.cards.get(payload.get('card'))
        key=payload.get('option')
        if prepare and (not card or not self.store.installed(card['id'])):return {'prepared':False}
        if not card or key not in tests_for(card):raise ValueError('Choose a special graphic for this card.')
        validated=self.validate_deck({'name':'Graphic test','items':[{'id':'test','card':card['id'],'options':payload.get('options',{}),'duration':6}]})['items'][0]
        options=validated['options'];group=None
        target=str(options.get(key,'device'))
        if target=='none':
            if prepare:return {'prepared':False}
            raise ValueError('This graphic is set to Do not show. Choose a display or group to test it.')
        if target in ('group','group_wall','wall') or target.startswith('group:'):
            group=self.graphic_group(ident,target)
        targets=group['members'] if group else [ident]
        known={d['id']:d for d in self.displays()};widths=[]
        for member in targets:
            self.selected(member)
            info=known.get(member)
            if not info or info.get('width') not in (64,128):raise ValueError('Refresh the display status before testing a graphic.')
            widths.append((member,info['width']))
        width=sum(w for _,w in widths)
        if width>512:raise ValueError('Test graphics support a group up to 512 pixels wide.')
        request=await self.render(validated,width,device_id=ident,request_only=True)
        request.update(test_graphic=key,card_metadata=card)
        started=time.monotonic()
        cache_key=hashlib.sha256(json.dumps([request,widths],sort_keys=True).encode()).hexdigest()
        cached=self.graphic_prepared.get(cache_key)
        if cached and time.monotonic()-cached[0]<900:event,slices=cached[1:]
        else:
            task=self.graphic_jobs.get(cache_key)
            if task is None:
                async def build():
                    # Share preparation with an arriving Test; never send from this task.
                    async with self.lock:
                        try:result=await self.run_worker(request)
                        finally:await self.store.collect(self.used())
                    event=result.get('event')
                    if not event or not event.get('body'):raise ValueError('This test graphic could not render. Nothing was sent.')
                    body=base64.b64decode(event['body'],validate=True)
                    if group:slices=await self.prepared_slices(body,widths)
                    else:
                        await self.prepared_frames(body,width)
                        slices=[(ident,width,event['body'])]
                    if not event.get('warning'):
                        size=len(event['body'])+sum(len(body) for _,_,body in slices)
                        while self.graphic_prepared and (len(self.graphic_prepared)>=8 or size+sum(len(value[1]['body'])+sum(len(body) for _,_,body in value[2]) for value in self.graphic_prepared.values())>32*1024*1024):
                            self.graphic_prepared.pop(next(iter(self.graphic_prepared)))
                        if size<=32*1024*1024:self.graphic_prepared[cache_key]=(time.monotonic(),event,slices)
                    return event,slices
                task=asyncio.create_task(build());self.graphic_jobs[cache_key]=task
                def finished(completed):
                    if self.graphic_jobs.get(cache_key) is completed:self.graphic_jobs.pop(cache_key,None)
                    if not completed.cancelled():completed.exception()
                task.add_done_callback(finished)
            event,slices=await asyncio.shield(task)
        if prepare:return {'prepared':True}
        render_ms=round((time.monotonic()-started)*1000)
        entries=[];event_id='test-'+uuid.uuid4().hex
        for member,member_width,body in slices:
            entries.append((member,{**event,'body':body,'source':'test','event_id':event_id,'start_at':0,**({'wall_members':targets,'wall_width':member_width} if group else {})}))
        if group:
            ready_at=time.time()+WALL_START_LEAD
            for _,payload in entries:payload['start_at']=ready_at
        await self.pipeline.submit(entries)
        return {'queued':True,'render_ms':render_ms,'displays':len(widths),'message':'Test graphic queued'+(' for the group' if group else '')+'. '+(event.get('warning','')+' ' if event.get('warning') else '')+'The deck continues with the next card after the interrupt.'}

    def register(self):
        routes=self.app.router
        async def object_data(request):
            data=await request.json()
            if not isinstance(data,dict):raise ValueError('Use a valid form.')
            return data
        async def state(request):return web.json_response(self.public())
        async def standings_groups(request):return web.json_response(await self.standings_groups(await object_data(request)))
        async def prepare_graphic(request):return web.json_response(await self.test_graphic(await object_data(request),prepare=True))
        async def test_graphic(request):return web.json_response(await self.test_graphic(await object_data(request)))
        async def deck_save(request):
            payload=await object_data(request);ident=payload.get('id') or uuid.uuid4().hex
            if not isinstance(ident,str) or len(ident)>80:raise ValueError('Invalid deck.')
            value=self.validate_deck(payload,self.data['decks'].get(ident) or self.data['decks'].get(payload.get('copyFrom')))
            if ident not in self.data['decks'] and len(self.data['decks'])>=100:raise ValueError('Up to 100 decks are supported.')
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
            await self.save_display_settings(ident,value)
            return web.json_response(self.public())
        async def action(request):
            data=await object_data(request);ident=data.get('id');targets=self.data['groups'].get(ident,{}).get('members',[ident])
            if data.get('action') not in ('play','stop','reboot'):raise ValueError('Choose Play, Stop or Reboot.')
            for target in targets:self.selected(target)
            async def perform(target):
                if data['action']=='play':await self.play(target)
                elif data['action']=='stop':await self.stop(target)
                else:
                    self.restarting.add(target)
                    await self.stop(target,remember=False);await self.selected(target).request('/api/reboot',{})
            outcomes=await asyncio.gather(*(perform(target) for target in targets),return_exceptions=True)
            failures=[]
            names={d['id']:d['name'] for d in self.displays()}
            for target,result in zip(targets,outcomes):
                if isinstance(result,BaseException):
                    reason=str(result) or 'The action was interrupted. Check the display before trying again.'
                    self.runtime[target]={'playing':False,'error':reason}
                    if target in self.data['devices']:
                        self.data['devices'][target].update(playing=False,last_error=reason)
                    failures.append(names.get(target,target)+': '+reason)
            if failures:
                await self.save()
                raise ValueError('\n'.join(failures))
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
            try:body=await self.render(item,width)
            except CardSkipped:return web.Response(status=204,headers={'Cache-Control':'no-store'})
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
        async def update_cards(request):
            try:
                from card_updates import fetch,install
                catalog=await fetch(self.app['session'])
                async with self.lock:
                    changed=await install(self.store,catalog,self.used())
                    self.cache.clear();self.skipped.clear();self.artwork_timing.clear()
                    self.graphic_prepared.clear();self.frame_prepared.clear();self.slice_prepared.clear()
                return web.json_response({'state':self.public(),'message':('Card library updated. Saved decks and playback settings preserved.' if changed else 'Your card library is already up to date.')})
            except asyncio.CancelledError:raise
            except ValueError:raise
            except Exception as exc:
                logging.exception("Card library update failed")
                raise ValueError("Card update failed. Saved decks were not changed. Check LED Studio logs for details.") from exc
        async def custom_upload(request):
            if request.headers.get('X-Pixora-Trust-Code')!='yes':raise ValueError('Confirm that you trust this Python code before importing it.')
            from custom_cards import describe,MAX_SOURCE
            body=bytearray()
            async for chunk in request.content.iter_chunked(16384):
                body.extend(chunk)
                if len(body)>MAX_SOURCE:raise ValueError('Choose a Python card file smaller than 256 KB.')
            card=describe(bytes(body))
            async with self.lock:
                if card['id'] in self.used():raise ValueError('Remove this app from saved decks before replacing it.')
                await self.store.import_custom(bytes(body))
            return web.json_response(self.public())
        async def custom_delete(request):
            ident=request.match_info['ident']
            async with self.lock:
                if ident in self.used():raise ValueError('Remove this app from saved decks before deleting it.')
                await self.store.delete_custom(ident)
            return web.json_response(self.public())
        async def custom_download(request):
            card=self.store.cards.get(request.match_info['ident'])
            if not card or not card.get('custom'):raise ValueError('Custom app not found.')
            return web.FileResponse(self.store.custom_root/(card['id']+'.py'),headers={'Content-Disposition':'attachment; filename="'+card['module']+'.py"'})
        async def creator_brief(request):return web.FileResponse(Path(__file__).with_name('Pixora-Codex-Card-Brief.md'),headers={'Content-Disposition':'attachment; filename="Pixora-Codex-Card-Brief.md"'})
        async def custom_starter(request):return web.FileResponse(Path(__file__).with_name('custom_card_starter.py'),headers={'Content-Disposition':'attachment; filename="custom_card_starter.py"'})
        routes.add_post('/api/studio/custom-apps',custom_upload)
        routes.add_post('/api/studio/update-cards',update_cards)
        routes.add_delete('/api/studio/custom-apps/{ident}',custom_delete)
        routes.add_get('/api/studio/custom-apps/{ident}',custom_download)
        routes.add_get('/api/studio/creator-brief',creator_brief)
        routes.add_get('/api/studio/custom-starter',custom_starter)
        routes.add_post('/api/studio/test-graphic',test_graphic)
        routes.add_post('/api/studio/prepare-graphic',prepare_graphic)
        routes.add_post('/api/studio/standings-groups',standings_groups)
        routes.add_get('/api/studio',state);routes.add_post('/api/studio/decks',deck_save);routes.add_delete('/api/studio/decks/{ident}',deck_delete)
        routes.add_post('/api/studio/ha-action',ha_action);routes.add_post('/api/studio/devices/{ident}',device_save);routes.add_post('/api/studio/action',action);routes.add_get('/api/studio/preview',preview)
        routes.add_get('/api/studio/entities',entities);routes.add_post('/api/studio/settings',settings)
        routes.add_post('/api/studio/groups',groups);routes.add_delete('/api/studio/groups/{ident}',group_delete)
        routes.add_post('/api/studio/graphics',upload);routes.add_get('/api/studio/graphics/{ident}',graphic);routes.add_delete('/api/studio/graphics/{ident}',graphic_delete)
