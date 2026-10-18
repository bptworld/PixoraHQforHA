"""Bounded hub cache shared by isolated card workers; never stores delivery state."""
import hashlib
import io
import json
import os
import time
import uuid
from pathlib import Path


class GraphicCache:
    def __init__(self,root,revision):
        self.root=Path(root);self.revision=revision;self.asset_failures=0

    def path(self,kind,key):
        digest=hashlib.sha256(json.dumps([self.revision,kind,key],sort_keys=True,default=str).encode()).hexdigest()
        return self.root/(digest+'.cache')

    def get(self,kind,key,ttl=900):
        path=self.path(kind,key)
        try:
            stat=path.stat()
            if time.time()-stat.st_mtime>ttl or stat.st_size>5*1024*1024+36:return None
            stored=path.read_bytes()
            if stored[:4]!=b'PXC1' or hashlib.sha256(stored[36:]).digest()!=stored[4:36]:return None
            return stored[36:]
        except OSError:return None

    def put(self,kind,key,body):
        if not body or len(body)>5*1024*1024:return
        temp=None
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            path=self.path(kind,key);temp=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            temp.write_bytes(b'PXC1'+hashlib.sha256(body).digest()+body);os.replace(temp,path)
            files=sorted(self.root.glob('*.cache'),key=lambda p:p.stat().st_mtime,reverse=True)
            total=0
            for index,file in enumerate(files):
                total+=file.stat().st_size
                if index>=256 or total>64*1024*1024 or time.time()-file.stat().st_mtime>86400:file.unlink(missing_ok=True)
        except OSError:pass  # A full/unavailable cache must not stop a deck or interrupt.
        finally:
            if temp:
                try:temp.unlink(missing_ok=True)
                except OSError:pass

    def install(self,utils):
        """Preserve Cloud's priority warm calls across short-lived local workers."""
        warm=[]
        original_json=utils.fetch_json_request
        def fetch_json(url,seconds=600):
            body=self.get('provider-json',url,max(0,seconds))
            if body:
                try:return json.loads(body)
                except ValueError:pass
            result=original_json(url,seconds=seconds)
            self.put('provider-json',url,json.dumps(result).encode())
            return result
        def cached(key,render):
            body=self.get('priority',key)
            if body:return body
            failures=self.asset_failures
            body=render()
            if self.asset_failures==failures:self.put('priority',key,body)
            return body
        def prepare(key,render):
            # Card warm callbacks carry the currently playing team's artwork.
            for value in getattr(render,'__defaults__',()) or ():
                if isinstance(value,dict) and any(k in value for k in ('abbreviation','displayName','logo')):
                    warm.append(dict(value));break
            try:return cached(key,render)
            except Exception:return None
        utils.fetch_json_request=fetch_json
        utils.cached_priority_graphic=cached
        utils.warm_priority_graphic=prepare
        return warm

    def install_images(self):
        """Reuse public image downloads, without caching scoreboards or failures."""
        import urllib.request
        from urllib.parse import urlsplit
        from PIL import Image
        original=urllib.request.urlopen
        def urlopen(request,*args,**kwargs):
            url=request.full_url if isinstance(request,urllib.request.Request) else str(request)
            parts=urlsplit(url)
            eligible=parts.scheme=='https' and parts.path.lower().endswith(('.png','.jpg','.jpeg','.webp','.gif'))
            if isinstance(request,urllib.request.Request) and (request.data or request.get_header('Authorization')):eligible=False
            if not eligible:return original(request,*args,**kwargs)
            body=self.get('image',url,86400)
            if not body:
                try:
                    with original(request,*args,**kwargs) as response:body=response.read(5*1024*1024+1)
                    with Image.open(io.BytesIO(body)) as image:image.verify()
                    self.put('image',url,body)
                except Exception:
                    self.asset_failures+=1
                    raise
            response=io.BytesIO(body);response.status=200;response.headers={};response.getcode=lambda:200
            return response
        urllib.request.urlopen=urlopen
