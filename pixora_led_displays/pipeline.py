"""Durable hub-owned priority delivery. Consumed writes are never replayed."""
import asyncio
import base64
import io
import json
import os
import time
import uuid
from pathlib import Path
from PIL import Image,ImageOps,ImageSequence


def normalize_image(body,width):
    if not body or len(body)>5*1024*1024:raise ValueError('Choose an image smaller than 5 MB.')
    with Image.open(io.BytesIO(body)) as image:
        if image.width*image.height>16000000:raise ValueError('Image exceeds 16 million pixels.')
        frames=[];timing=[]
        for index,frame in enumerate(ImageSequence.Iterator(image)):
            if index>=240:raise ValueError('Animation exceeds 240 frames.')
            rgba=ImageOps.exif_transpose(frame).convert('RGBA')
            rgb=Image.alpha_composite(Image.new('RGBA',rgba.size,'black'),rgba).convert('RGB')
            frames.append(ImageOps.pad(rgb,(width,32),color='black'))
            timing.append(max(20,min(60000,int(frame.info.get('duration',100)))))
        out=io.BytesIO()
        if len(frames)>1:frames[0].save(out,'WEBP',save_all=True,append_images=frames[1:],duration=timing,loop=0,lossless=True,method=0)
        else:frames[0].save(out,'PNG')
        return out.getvalue()


class Pipeline:
    def __init__(self,root,studio):
        self.root,self.studio=root,studio;self.file=root/'pipeline.json'
        self.data=json.loads(self.file.read_text()) if self.file.exists() else {'states':{},'queues':{},'inflight':{},'seen':{}}
        self.lock=asyncio.Lock();self.jobs={};self.busy={};self.idle={};self.wires={};self.errors=self.data.setdefault('errors',{});self.blocked=set()
        # An interrupted in-flight request may have reached the panel. Do not replay it.
        for ident in self.data['inflight']:
            self.errors[ident]='Previous priority delivery was interrupted; it was not resent.'
            self.data['queues'][ident]=[]
        self.data['inflight']={}

    def signals(self,ident):
        if ident not in self.busy:
            self.busy[ident]=asyncio.Event();self.idle[ident]=asyncio.Event();self.idle[ident].set()
        return self.busy[ident],self.idle[ident]

    def persist(self):
        self.root.mkdir(parents=True,exist_ok=True);temp=self.file.with_suffix('.tmp')
        temp.write_text(json.dumps(self.data,separators=(',',':')),encoding='utf-8');os.chmod(temp,0o600);os.replace(temp,self.file)

    async def commit(self):
        task=asyncio.create_task(asyncio.to_thread(self.persist))
        try:await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task,return_exceptions=True);raise

    def start(self,ident):
        busy,idle=self.signals(ident);busy.set();idle.clear()
        if ident not in self.jobs or self.jobs[ident].done():
            task=asyncio.create_task(self.consume(ident));self.jobs[ident]=task
            def finished(completed):
                if not completed.cancelled():completed.exception()
                if self.data['queues'].get(ident) and ident not in self.errors and not completed.cancelled():self.start(ident)
            task.add_done_callback(finished)

    async def submit(self,entries,state_key=None,state=None):
        """Commit event history and queues together before delivery can begin."""
        async with self.lock:
            previous=json.loads(json.dumps(self.data));targets=set()
            try:
                for ident,payload in entries:
                    ident=str(ident);self.studio.selected(ident)
                    if ident in self.errors:raise ValueError(self.errors[ident])
                    queue=self.data['queues'].setdefault(ident,[])
                    key=payload.get('event_id') or uuid.uuid4().hex
                    if key in self.data['seen'].get(ident,[]):continue
                    if len(queue)>=32 or sum(len(json.dumps(p)) for p in queue)+len(json.dumps(payload))>8*1024*1024:
                        raise ValueError('Display priority queue is full.')
                    entry={**payload,'event_id':key,'expires':time.time()+300}
                    queue.append(entry);targets.add(ident)
                    seen=self.data['seen'].setdefault(ident,[]);seen.append(key);del seen[:-128]
                if state_key is not None:self.data['states'][state_key]=state or {}
                if len(json.dumps(self.data['states']))>2*1024*1024:raise ValueError('Event history exceeds the hub limit.')
                await self.commit()
            except BaseException:
                self.data=previous;self.errors=self.data.setdefault("errors",{});raise
            for ident in targets:self.start(ident)

    async def write(self,ident,operation):
        from client import DisplayBusy,PriorityMessageActive
        async with self.wires.setdefault(ident,asyncio.Lock()):
            if ident in self.errors or ident in self.blocked:raise ValueError(self.errors.get(ident,'Delivery is paused after an uncertain write. Check the display, then press Play.'))
            for attempt in range(5):
                try:return await operation()
                except DisplayBusy:
                    # Only explicit rejection is retried. Timeout/unknown outcomes escape immediately.
                    if attempt==4:raise
                    await asyncio.sleep(.02)
                except PriorityMessageActive:raise
                except BaseException:
                    self.blocked.add(ident);raise

    async def wait_ready(self,ident):
        _,idle=self.signals(ident);await idle.wait()
        if ident in self.errors or ident in self.blocked:raise ValueError(self.errors.get(ident,'Delivery paused after an uncertain write. Check the display, then press Play.'))

    async def delay(self,ident,seconds):
        """Return remaining deck dwell immediately when a priority item arrives."""
        if not ident:
            await asyncio.sleep(seconds);return 0
        busy,_=self.signals(ident);started=time.monotonic()
        if busy.is_set():return seconds
        try:await asyncio.wait_for(busy.wait(),seconds)
        except asyncio.TimeoutError:return 0
        return max(0,seconds-(time.monotonic()-started))

    async def consume(self,ident):
        busy,idle=self.signals(ident)
        try:
            while True:
                async with self.lock:
                    queue=self.data['queues'].setdefault(ident,[])
                    queue[:]=[p for p in queue if p.get('expires',0)>time.time()]
                    if not queue:break
                    # HA messages precede queued card events; each class remains FIFO.
                    index=next((i for i,p in enumerate(queue) if p.get('source')=='ha'),0)
                    payload=queue.pop(index);self.data['inflight'][ident]=payload['event_id'];await self.commit()
                start=payload.get('start_at',0)
                client=self.studio.selected(ident)
                info=await client.info()
                if info.get('active') and info.get('owner')!='deck':await asyncio.sleep(min(300,max(0,float(info.get('remaining',0)))))
                if start:
                    if time.time()>start+.5:
                        async with self.lock:self.data['inflight'].pop(ident,None);await self.commit()
                        continue
                    if start>time.time():await asyncio.sleep(start-time.time())
                if payload.get('message') is not None:
                    await self.write(ident,lambda:client.show(payload['message'],payload.get('color',[255,255,255]),payload['duration']))
                    await asyncio.sleep(payload['duration'])
                else:
                    body=base64.b64decode(payload['body'],validate=True)
                    await self.studio.deliver(client,body,info['width'],payload['duration'],owner='message',once=payload.get('once',False),wire_ident=ident)
                async with self.lock:self.data['inflight'].pop(ident,None);await self.commit()
        except asyncio.CancelledError:raise
        except Exception:
            # Never automatically send queued work behind an uncertain physical write.
            async with self.lock:
                self.errors[ident]='Priority delivery could not be confirmed. Playback paused; the command was not retried. Check the display, then press Play.'
                self.data['queues'][ident]=[];self.data['inflight'].pop(ident,None)
                await self.commit()
            self.studio.runtime[ident]={'playing':False,'error':self.errors[ident]}
            if hasattr(self.studio,'data'):
                self.studio.data['devices'].get(ident,{})['playing']=False
                await self.studio.save()
        finally:
            busy.clear();idle.set()

    async def close(self):
        tasks=list(self.jobs.values())
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);self.jobs.clear()
