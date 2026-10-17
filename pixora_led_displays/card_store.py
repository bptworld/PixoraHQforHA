"""Download only cards referenced by local decks; shared helpers remain installed."""
import asyncio,hashlib,json,os,shutil,uuid
from pathlib import Path,PurePosixPath
import aiohttp

class CardStore:
    def __init__(self,session,root):
        self.session,self.root=session,root
        self.catalog=json.loads(Path(__file__).with_name('card_catalog.json').read_text(encoding='utf-8'))
        self.cards={c['id']:c for c in self.catalog['cards']}
        self.lock=asyncio.Lock()
        self.root.mkdir(parents=True,exist_ok=True)

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
                    url='https://raw.githubusercontent.com/bptworld/pixora/'+self.catalog['commit']+'/cards/'+name
                    try:
                        async with self.session.get(url,allow_redirects=False,timeout=aiohttp.ClientTimeout(total=25)) as response:
                            if response.status!=200:raise ValueError('Could not download this card. Your deck was not changed.')
                            body=bytearray()
                            async for chunk in response.content.iter_chunked(65536):
                                body.extend(chunk)
                                if len(body)>meta['size']:raise ValueError('Card file verification failed.')
                    except (aiohttp.ClientError,asyncio.TimeoutError) as exc:
                        raise ValueError('Card download failed. Your deck was not changed.') from exc
                    if len(body)!=meta['size'] or hashlib.sha256(body).hexdigest()!=meta['sha256']:raise ValueError('Card file verification failed.')
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
