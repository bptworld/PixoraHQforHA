"""Verified metadata-only card releases, independent of the HA app release."""
import asyncio,hashlib,json,os,re,shutil,uuid
from pathlib import Path,PurePosixPath
import aiohttp

URL='https://raw.githubusercontent.com/bptworld/pixora/main/cards/ha-catalog.json'
MAX_CATALOG=2*1024*1024

def safe_path(value):
    return isinstance(value,str) and bool(value) and len(value)<240 and '\\' not in value and ':' not in value and not PurePosixPath(value).is_absolute() and all(p not in ('','..','.') for p in value.split('/'))

def validate(data):
    try:
        if len(json.dumps(data,allow_nan=False).encode())>MAX_CATALOG:raise ValueError('Large catalog')
    except (TypeError,ValueError,RecursionError) as exc:raise ValueError('Invalid card library JSON.') from exc
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('renderer_api')!=1:
        raise ValueError('This card library needs a newer LED Studio app. Update the app first.')
    if not isinstance(data.get('commit'),str) or not re.fullmatch('[0-9a-f]{40}',data['commit']):raise ValueError('Invalid card library revision.')
    files=data.get('files');cards=data.get('cards');shared=data.get('shared_files')
    if not isinstance(files,dict) or not 1<=len(files)<=3000 or not isinstance(cards,list) or not 1<=len(cards)<=1000 or not isinstance(shared,list):raise ValueError('Invalid card library metadata.')
    total=0
    for name,meta in files.items():
        if not safe_path(name) or not isinstance(meta,dict) or not re.fullmatch('[0-9a-f]{64}',str(meta.get('sha256',''))) or type(meta.get('size')) is not int or not 0<meta['size']<=20*1024*1024 or meta.get('custom'):raise ValueError('Invalid card dependency metadata.')
        if not safe_path(meta.get('source_path','cards/'+name)):raise ValueError('Invalid public card source.')
        if 'source_commit' in meta and not re.fullmatch('[0-9a-f]{40}',str(meta['source_commit'])):raise ValueError('Invalid dependency revision.')
        total+=meta['size']
    if total>200*1024*1024 or any(not isinstance(n,str) or n not in files for n in shared):raise ValueError('Invalid shared dependencies.')
    seen=set()
    for card in cards:
        if not isinstance(card,dict):raise ValueError('Invalid card metadata.')
        ident=card.get('id');module=card.get('module')
        if not isinstance(ident,str) or not re.fullmatch('[a-z][a-z0-9_]{0,79}',ident) or ident in seen or not isinstance(module,str) or not re.fullmatch('[a-zA-Z_][a-zA-Z0-9_]{0,79}',module) or card.get('custom'):raise ValueError('Invalid card identity.')
        seen.add(ident)
        if any(not isinstance(card.get(k),str) or not 1<=len(card[k])<=200 for k in ('name','category')):raise ValueError('Invalid card title.')
        dependencies=card.get('files')
        if not isinstance(dependencies,list) or not dependencies or any(not isinstance(n,str) or n not in files for n in dependencies) or not any(n in dependencies for n in (module+'.py','addons/'+module+'.py')):raise ValueError('Missing card dependencies.')
        options=card.get('options',[])
        if not isinstance(options,list) or len(options)>100:raise ValueError('Invalid card options.')
        keys=set()
        for option in options:
            if not isinstance(option,dict) or not isinstance(option.get('key'),str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,79}',option['key']) or option['key'] in keys or not isinstance(option.get('label'),str) or option.get('type') not in ('text','password','number','checkbox','select','multiselect','date','hubitatDevices','smartthingsDevices'):raise ValueError('Invalid card option.')
            keys.add(option['key'])
            if option['type'] in ('select','multiselect'):
                choices=option.get('choices')
                if not isinstance(choices,list) or len(choices)>3000 or any(not isinstance(c,str) and not (isinstance(c,dict) and isinstance(c.get('value'),(str,int,float)) and isinstance(c.get('label'),str)) for c in choices):raise ValueError('Invalid card choices.')
        preview=card.get('previewUrl','')
        if preview and not preview.startswith('https://raw.githubusercontent.com/bptworld/pixora/'):raise ValueError('Invalid card preview source.')
    return data

async def fetch(session):
    try:
        async with session.get(URL,allow_redirects=False,timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status!=200:raise ValueError('Could not check the card library. Your current cards are unchanged.')
            body=bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body)>MAX_CATALOG:raise ValueError('Card library metadata is too large.')
        return validate(json.loads(body))
    except (aiohttp.ClientError,asyncio.TimeoutError,UnicodeError,json.JSONDecodeError,RecursionError) as exc:
        raise ValueError('Could not check the card library. Your current cards are unchanged.') from exc

async def install(store,catalog,used):
    """Stage a complete generation, then atomically publish a durable pointer."""
    validate(catalog)
    async with store.lock:
        if catalog['commit']==store.catalog['commit']:return 0
        old=store.catalog
        incoming=json.loads(json.dumps(catalog))
        # Retain previously downloaded common helpers, even when no deck uses them.
        for name in old.get('shared_files',[]):
            if name not in incoming['files']:
                incoming['files'][name]={**old['files'][name],'source_commit':old['files'][name].get('source_commit',old['commit'])}
            if name not in incoming['shared_files']:incoming['shared_files'].append(name)
        validate(incoming)
        folder=store.root.parent/('card-generation-'+uuid.uuid4().hex)
        pointer=store.root.parent/'card-library.json';temp=pointer.with_suffix('.tmp')
        staged=store.__class__.__new__(store.__class__)
        staged.session=store.session;staged.root=folder;staged.custom_root=store.custom_root;staged.lock=asyncio.Lock()
        staged.catalog=json.loads(json.dumps(incoming));staged.cards={c['id']:c for c in staged.catalog['cards']}
        try:
            folder.mkdir()
            for card in store.cards.values():
                if card.get('custom'):
                    body=(store.custom_root/(card['id']+'.py')).read_bytes()
                    staged.register_custom(json.loads(json.dumps(card)),body)
            if any(ident not in staged.cards for ident in used):raise ValueError('The new library removed a card used by a saved deck. Your current cards are unchanged.')
            # Copy only already verified installed files; all changed bytes go
            # through normal bounded immutable-commit downloads below.
            for name,meta in staged.catalog['files'].items():
                source=store.root/name
                if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest()==meta['sha256']:
                    target=folder/name;target.parent.mkdir(parents=True,exist_ok=True)
                    try:os.link(source,target)
                    except OSError:shutil.copyfile(source,target)
            await staged.ensure(used)
            # Existing shared helpers also receive verified updates, without
            # downloading unused card modules or their private assets.
            retained=[n for n in incoming['shared_files'] if (store.root/n).is_file()]
            staged.cards['_retained']={'files':retained}
            await staged.ensure({'_retained'});del staged.cards['_retained']
            for path in folder.rglob('*.py'):
                try:compile(path.read_bytes(),str(path),'exec')
                except (SyntaxError,ValueError) as exc:raise ValueError('An updated card contains invalid Python. Your current cards are unchanged.') from exc
            from standings import configure
            from special_graphics import configure_scoring_choices
            configure(staged.cards);configure_scoring_choices(staged.cards)
            with temp.open('w',encoding='utf-8') as output:
                json.dump({'generation':folder.name,'catalog':incoming},output);output.flush();os.fsync(output.fileno())
            os.replace(temp,pointer)
            changed=sum(old.get('files',{}).get(n)!=meta for n,meta in incoming['files'].items())
            store.root,store.catalog,store.cards=folder,staged.catalog,staged.cards
            return max(1,changed)
        except BaseException:
            shutil.rmtree(folder,ignore_errors=True);raise
        finally:temp.unlink(missing_ok=True)
