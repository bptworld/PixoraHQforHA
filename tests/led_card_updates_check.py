"""Independent library updates: verified staging, restart, custom apps and rollback."""
import asyncio,copy,hashlib,json,sys,tempfile
from pathlib import Path
APP=Path(__file__).resolve().parents[1]/'pixora_led_displays'
sys.path.insert(0,str(APP))
from card_store import CardStore
from card_updates import validate,fetch,install,URL

def catalog(revision,bodies):
    return {'schema':1,'renderer_api':1,'commit':revision*40,'shared_files':['helper.py'],
      'files':{name:{'size':len(body),'sha256':hashlib.sha256(body).hexdigest()} for name,body in bodies.items()},
      'cards':[{'id':name,'module':name,'name':name,'category':'Fun','options':[],
        'files':['addons/'+name+'.py','helper.py']} for name in ('one','unused')]}

class Response:
    status=200
    def __init__(self,body):self.body=body;self.content=self
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def iter_chunked(self,size):yield self.body
class Session:
    def __init__(self):self.requests=[];self.bodies={};self.manifest=None;self.bad=False
    def get(self,url,**kwargs):
        self.requests.append(url)
        assert kwargs['allow_redirects'] is False
        if url==URL:return Response(json.dumps(self.manifest).encode())
        name=url.split('/cards/',1)[1]
        return Response(b'corrupt' if self.bad else self.bodies[name])

async def check():
    validate(json.loads((APP/'card_catalog.json').read_text()))
    session=Session()
    old={'addons/one.py':b'VALUE=1\n','addons/unused.py':b'VALUE=0\n','helper.py':b'HELPER=1\n'}
    new={**old,'addons/one.py':b'VALUE=2\n','helper.py':b'HELPER=2\n'}
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)/'downloaded-cards';store=CardStore(session,root)
        store.catalog=catalog('a',old);store.cards={c['id']:c for c in store.catalog['cards']}
        session.bodies=old
        await store.ensure({'one'})
        # A shared helper removed from the new catalog still belongs on the hub.
        legacy=b'LEGACY=1\n';(root/'legacy.py').write_bytes(legacy)
        store.catalog['files']['legacy.py']={'size':len(legacy),'sha256':hashlib.sha256(legacy).hexdigest()}
        store.catalog['shared_files'].append('legacy.py')
        custom=b'CARD_ID="mine"\nCARD_NAME="Mine"\nCARD_OPTIONS=[]\ndef render(options=None): return b"mine"\n'
        ident=await store.import_custom(custom)
        await store.ensure({ident})
        session.requests=[];session.bodies=new;session.manifest=catalog('b',new)
        incoming=await fetch(session)
        assert await install(store,incoming,{'one',ident})>0
        assert (store.root/'addons/one.py').read_bytes()==new['addons/one.py']
        assert (store.root/'helper.py').read_bytes()==new['helper.py']
        assert (store.root/'legacy.py').read_bytes()==legacy
        assert not (store.root/'addons/unused.py').exists()
        assert not any('addons/unused.py' in url for url in session.requests)
        assert (store.custom_root/(ident+'.py')).read_bytes()==custom
        assert (store.root/('addons/'+ident+'.py')).read_bytes()==custom
        assert (root/'addons/one.py').read_bytes()==old['addons/one.py'],'In-flight old render lost its snapshot'
        restored=CardStore(session,root)
        assert restored.catalog['commit']=='b'*40 and restored.root==store.root
        assert restored.cards[ident]['custom']
        requests=len(session.requests);session.bad=True
        await restored.ensure({'one',ident})
        assert len(session.requests)==requests,'Restart needed a download for already verified cards'
        session.bad=False
        assert await install(restored,incoming,{'one',ident})==0
        pointer=(Path(folder)/'card-library.json').read_bytes();active=restored.root
        broken={**new,'addons/one.py':b'VALUE=3\n'}
        session.bodies=broken;session.bad=True
        try:await install(restored,catalog('c',broken),{'one',ident})
        except ValueError:pass
        else:raise AssertionError('Corrupt card update accepted')
        assert restored.root==active and (Path(folder)/'card-library.json').read_bytes()==pointer
        assert (active/'addons/one.py').read_bytes()==new['addons/one.py']
        session.bad=False
        invalid={**new,'addons/one.py':b'def broken(\n'}
        session.bodies=invalid
        try:await install(restored,catalog('d',invalid),{'one',ident})
        except ValueError:pass
        else:raise AssertionError('Broken Python accepted')
        assert restored.root==active and (Path(folder)/'card-library.json').read_bytes()==pointer
        assert len(list(Path(folder).glob('card-generation-*')))==1,'Failed staging directories leaked'
        for mutate in (lambda c:c.update(renderer_api=2),lambda c:c['files'].update({'../escape.py':next(iter(c['files'].values()))}),lambda c:c['cards'].append(c['cards'][0]),lambda c:c['cards'][0].update(files=['missing.py'])):
            bad=copy.deepcopy(incoming);mutate(bad)
            try:validate(bad)
            except ValueError:pass
            else:raise AssertionError('Invalid catalog accepted')
    # Exercise the same local HTTP route used by the Ingress button.
    from aiohttp import web
    from aiohttp.test_utils import TestClient,TestServer
    sys.path.insert(0,str(APP/'custom_components/pixora_local'))
    from studio import Studio
    with tempfile.TemporaryDirectory() as folder:
        app=web.Application();app['session']=session
        studio=Studio(app,Path(folder),lambda ident:None,lambda:[])
        studio.register();session.manifest=catalog('b',new);session.bodies=new
        studio.store.catalog=catalog('a',old);studio.store.cards={c['id']:c for c in studio.store.catalog['cards']}
        studio.data['decks']={'saved':{'name':'Saved','items':[{'id':'one','card':'one','options':{},'enabled':True,'duration':10}]}}
        studio.data['devices']={'panel':{'playing':True,'deck':'saved','brightness':60}}
        before=copy.deepcopy(studio.data)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/api/studio/update-cards',json={});assert response.status==200
            result=await response.json()
            assert result['state']['cardLibraryRevision']=='bbbbbbbb' and 'updated' in result['message']
            assert studio.data==before,'Library update changed saved decks or playback intent'
            response=await client.post('/api/studio/update-cards',json={})
            assert 'already up to date' in (await response.json())['message']
    print('Card updates passed: 142-card compatibility, immutable checksums, used-only downloads, shared-helper retention, custom-app isolation, restart persistence, no-op repeat, old render snapshots, corruption/syntax rollback and invalid manifest rejection.')

asyncio.run(check())
