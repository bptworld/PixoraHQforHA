"""Local display studio: saved decks, downloaded cards, graphics and LAN playback."""
import asyncio,base64,hashlib,hmac,io,json,os,sys,time,uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from aiohttp import web,ClientTimeout
from PIL import Image,ImageOps,ImageSequence
from card_store import CardStore
from client import PriorityMessageActive

class Studio:
    def __init__(self,app,root,selected,displays):
        self.app,self.root,self.selected,self.displays=app,root,selected,displays
        self.file=root/'studio.json';self.lock=asyncio.Lock();self.io_lock=asyncio.Lock();self.jobs={};self.runtime={};self.cache={}
        self.data=json.loads(self.file.read_text(encoding='utf-8')) if self.file.exists() else {'decks':{},'devices':{},'groups':{},'graphics':{},'settings':{'timezone':os.environ.get('TZ','UTC'),'timeFormat':'12','temperatureUnits':'F'}}
        self.store=CardStore(app['session'],root/'downloaded-cards')
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
        result['runtime']=self.runtime
        result['cards']=[{k:v for k,v in card.items() if k not in ('files','module')}|{'installed':self.store.installed(card['id'])} for card in self.store.cards.values()]
        result['displays']=sorted([{k:v for k,v in d.items() if k!='key'} for d in self.displays()],key=lambda d:d['name'].casefold())
        return result

    async def stop(self,ident,remember=True):
        task=self.jobs.pop(ident,None)
        if task:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
        self.runtime[ident]={'playing':False}
        if remember and ident in self.data['devices']:
            self.data['devices'][ident]['playing']=False
            await self.save()

    async def shutdown(self):
        for ident in list(self.jobs):await self.stop(ident,remember=False)

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
            self.cache.clear()
            await self.store.collect(self.used())

    async def ha(self,path):
        token=os.environ.get('SUPERVISOR_TOKEN')
        if not token:raise ValueError('Home Assistant API is unavailable. Restart the LED Displays app after updating it.')
        async with self.app['session'].get('http://supervisor/core/api/'+path,headers={'Authorization':'Bearer '+token},allow_redirects=False,timeout=ClientTimeout(total=10)) as response:
            if response.status!=200:raise ValueError('Could not read Home Assistant. Check the entity or HA connection.')
            return await response.json()

    async def render(self,item,width):
        if 'graphic' in item:return (self.root/'graphics'/item['graphic']).read_bytes()
        card=self.store.cards[item['card']]
        await self.store.ensure({card['id']})
        options=dict(item.get('options',{}));options['_target']='matrixportal-s3-'+str(width)+'x32'
        request={'root':str(self.store.root.resolve()),'module':card['module'],'width':width,'options':options,'settings':self.data['settings']}
        if card['id']=='home_assistant_entity':
            entity=options.get('entityId','')
            if not isinstance(entity,str) or not all(c.isalnum() or c in '._' for c in entity):raise ValueError('Choose a Home Assistant entity.')
            request['ha_state']=await self.ha('states/'+entity)
        encoded=json.dumps(request).encode()
        if len(encoded)>65536:raise ValueError('Card options are too large. Shorten the text values.')
        key=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
        cached=self.cache.get(key)
        ttl=1 if card['category'] in ('Fun',) or card['id'].startswith('clock') else 60
        if cached and time.monotonic()-cached[0]<ttl:return cached[1]
        env={k:v for k,v in os.environ.items() if k.upper() in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP','LANG','TZ','PYTHONIOENCODING')}
        async with self.store.lock:
            process=await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).with_name('card_worker.py')),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
            try:
                out,_=await asyncio.wait_for(process.communicate(json.dumps(request).encode()),30)
                if process.returncode or not out or len(out)>5*1024*1024:raise ValueError('This card could not render. Check its options and data-provider connection.')
            finally:
                if process.returncode is None:process.kill();await process.wait()
        if len(self.cache)>=32:self.cache.pop(next(iter(self.cache)))
        self.cache[key]=(time.monotonic(),out)
        return out

    async def send_frame(self,client,body,width,duration,owner='deck'):
        with Image.open(io.BytesIO(body)) as image:
            image=ImageOps.pad(ImageOps.exif_transpose(image).convert('RGB'),(width,32),color='black')
            payload={'rgb':base64.b64encode(image.tobytes()).decode(),'width':width,'height':32,'duration':duration,'owner':owner}
        await client.request('/api/frame',payload)

    async def deliver(self,client,body,width,duration):
        with Image.open(io.BytesIO(body)) as image:
            frames=[]
            for index,frame in enumerate(ImageSequence.Iterator(image)):
                if index>=120:break
                out=io.BytesIO();frame.convert('RGB').save(out,'PNG')
                frames.append((out.getvalue(),max(.25,min(2,frame.info.get('duration',250)/1000))))
        if len(frames)==1:
            await self.send_frame(client,frames[0][0],width,min(300,duration+2))
            await asyncio.sleep(duration)
            return
        end=time.monotonic()+duration;position=0
        while time.monotonic()<end:
            pixels,delay=frames[position%len(frames)];position+=1
            await self.send_frame(client,pixels,width,min(300,max(1,int(end-time.monotonic())+2)))
            await asyncio.sleep(min(delay,max(0,end-time.monotonic())))

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
        self.jobs[ident]=asyncio.create_task(self.player(ident))

    async def player(self,ident):
        position=0;last_brightness=None
        try:
            while True:
                cfg=self.data['devices'].get(ident,{})
                deck=self.data['decks'].get(cfg.get('deck'),{})
                items=[i for i in deck.get('items',[]) if i['enabled']]
                if not items:raise ValueError('Deck has no enabled cards.')
                client=self.selected(ident);info=await client.info()
                brightness=cfg.get('quietBrightness',0) if self.quiet(cfg) else cfg.get('brightness',60)
                if brightness!=last_brightness:
                    await client.request('/api/settings',{'brightness':brightness});last_brightness=brightness
                if info.get('active') and info.get('owner')!='deck':
                    self.runtime[ident]={'playing':True,'status':'HA message has priority'}
                    await asyncio.sleep(min(10,max(1,info.get('remaining',1))))
                    continue
                if self.quiet(cfg) and brightness==0:
                    self.runtime[ident]={'playing':True,'status':'Quiet hours'}
                    await asyncio.sleep(10);continue
                item=items[position%len(items)];position+=1
                body=await self.render(item,info['width'])
                # Re-read after potentially slow provider rendering: never overwrite a new HA message.
                current=await client.info()
                if current.get('active') and current.get('owner')!='deck':position-=1;continue
                name=self.store.cards[item['card']]['name'] if 'card' in item else self.data['graphics'][item['graphic']]['name']
                self.runtime[ident]={'playing':True,'status':name,'item':item['id']}
                try:
                    await self.deliver(client,body,info['width'],item['duration'])
                except PriorityMessageActive:
                    position-=1
                    await asyncio.sleep(1)
                    continue

        except asyncio.CancelledError:raise
        except Exception as exc:
            # A failed or uncertain panel write pauses the deck. Never retry that write.
            self.runtime[ident]={'playing':False,'error':str(exc) if isinstance(exc,ValueError) else 'Playback stopped. Check the card and display connection.'}
            self.data['devices'].get(ident,{})['playing']=False
            self.data['devices'].get(ident,{})['last_error']=self.runtime[ident]['error']
            await self.save()

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
            else:raise ValueError('Choose Play or Pause.')
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
                image=ImageOps.exif_transpose(image).convert('RGBA');out=io.BytesIO();image.save(out,'PNG');body=out.getvalue()
            ident=hashlib.sha256(body).hexdigest()+'.png';folder=self.root/'graphics';folder.mkdir(parents=True,exist_ok=True)
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
