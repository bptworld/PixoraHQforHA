"""Download only cards referenced by local decks; shared helpers remain installed."""
import asyncio,hashlib,json,os,shutil,uuid,logging
from custom_cards import describe
from pathlib import Path,PurePosixPath
import aiohttp

class CardStore:
    def __init__(self,session,root):
        self.session,self.root=session,root
        self.catalog=json.loads(Path(__file__).with_name('card_catalog.json').read_text(encoding='utf-8'))
        self.cards={c['id']:c for c in self.catalog['cards']}
        from standings import configure
        configure(self.cards)
        from special_graphics import configure_scoring_choices
        configure_scoring_choices(self.cards)
        self.lock=asyncio.Lock()
        self.root.mkdir(parents=True,exist_ok=True)
        self.custom_root=self.root.parent/'custom-cards'
        self.custom_root.mkdir(parents=True,exist_ok=True)
        for path in self.custom_root.glob('custom_*.py'):
            try:
                body=path.read_bytes();card=describe(body)
                if path.stem!=card['id']:raise ValueError('Custom card ID does not match its filename.')
                self.register_custom(card,body)
            except (ValueError,OSError):logging.warning('Could not load custom card %s; reimport the original file.',path.name)

    def register_custom(self,card,body):
        if card['id'] in self.cards and not self.cards[card['id']].get('custom'):raise ValueError('A custom app cannot replace a library card.')
        name='addons/'+card['module']+'.py'
        card['files']=sorted(set(self.catalog.get('shared_files',[]))|{name})
        self.cards[card['id']]=card
        self.catalog['files'][name]={'sha256':hashlib.sha256(body).hexdigest(),'size':len(body),'custom':True}

    async def import_custom(self,body):
        card=describe(body)
        async with self.lock:
            if card['id'] in self.cards and not self.cards[card['id']].get('custom'):raise ValueError('A custom app cannot replace a library card.')
            if card['id'] not in self.cards and sum(bool(c.get('custom')) for c in self.cards.values())>=50:
                raise ValueError('Up to 50 custom apps are supported.')
            path=self.custom_root/(card['id']+'.py');temp=path.with_suffix('.tmp')
            try:
                temp.write_bytes(body);os.chmod(temp,0o600);os.replace(temp,path)
            finally:temp.unlink(missing_ok=True)
            self.register_custom(card,body)
        return card['id']

    async def delete_custom(self,ident):
        async with self.lock:
            card=self.cards.get(ident)
            if not card or not card.get('custom'):raise ValueError('Custom app not found.')
            (self.custom_root/(card['id']+'.py')).unlink(missing_ok=True)
            self.path('addons/'+card['module']+'.py').unlink(missing_ok=True)
            self.catalog['files'].pop('addons/'+card['module']+'.py',None)
            del self.cards[ident]


    def required(self, ids):
        if any(i not in self.cards for i in ids):raise ValueError('Choose a card from the library.')
        return {name for ident in ids for name in self.cards[ident]['files']}

    def path(self,name):
        if name not in self.catalog['files'] or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
            raise ValueError('Invalid card package path.')
        return self.root/name

    async def ensure(self,ids):
        async with self.lock:
            staged=[]
            try:
                for name in sorted(self.required(ids)):
                    path=self.path(name);meta=self.catalog['files'][name]
                    if path.is_file() and await asyncio.to_thread(lambda:hashlib.sha256(path.read_bytes()).hexdigest())==meta['sha256']:continue
                    if meta.get('custom'):
                        body=(self.custom_root/Path(name).name).read_bytes()
                        if hashlib.sha256(body).hexdigest()!=meta['sha256']:raise ValueError('Custom app changed on disk. Reimport it in My Apps.')
                        path.parent.mkdir(parents=True,exist_ok=True)
                        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(body);staged.append((temp,path))
                        continue
                    source=meta.get('source_path','cards/'+name)
                    if PurePosixPath(source).is_absolute() or '..' in PurePosixPath(source).parts:raise ValueError('Invalid public card source.')
                    url='https://raw.githubusercontent.com/bptworld/pixora/'+self.catalog['commit']+'/'+source
                    try:
                        async with self.session.get(url,allow_redirects=False,timeout=aiohttp.ClientTimeout(total=25)) as response:
                            if response.status!=200:raise ValueError('Could not download this card. Your deck was not changed.')
                            body=bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                body.extend(chunk)
                                if len(body)>meta['size']:raise ValueError('Card file verification failed for '+name+'. Your deck was not changed. Check for an LED Studio app update.')
                    except (aiohttp.ClientError,asyncio.TimeoutError) as exc:
                        raise ValueError('Card download failed. Your deck was not changed.') from exc
                    if len(body)!=meta['size'] or hashlib.sha256(body).hexdigest()!=meta['sha256']:raise ValueError('Card file verification failed for '+name+'. Your deck was not changed. Check for an LED Studio app update.')
                    path.parent.mkdir(parents=True,exist_ok=True)
                    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_bytes(body);staged.append((temp,path))
                for temp,path in staged:os.replace(temp,path)
            finally:
                for temp,_ in staged:temp.unlink(missing_ok=True)

    async def collect(self,ids):
        """Call only after the saved deck transaction succeeds and renders are stopped."""
        async with self.lock:
            keep=self.required(ids)|set(self.catalog.get('shared_files',[]))
            for path in self.root.rglob('*'):
                if path.is_file() and path.relative_to(self.root).as_posix() not in keep:path.unlink()
            for folder in sorted((p for p in self.root.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
                if not any(folder.iterdir()):folder.rmdir()

    def installed(self,ident):
        return ident in self.cards and all(self.path(name).is_file() for name in self.cards[ident]['files'])
