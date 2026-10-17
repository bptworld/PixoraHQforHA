"""Optional GitHub firmware checks; cards and HA automations remain entirely local."""
import asyncio
import hashlib
import re
import time
from urllib.parse import urlsplit
import aiohttp

REPO = 'bptworld/PixoraHQforHA'
MAX_SIZE = 2097152

def version(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', value or '')
    if not match: raise ValueError('Invalid firmware version.')
    return tuple(map(int,match.groups()))

async def bounded_body(response, limit):
    body=bytearray()
    async for chunk in response.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body)>limit: raise ValueError('Firmware download information exceeds the size limit.')
    return bytes(body)

class FirmwareUpdates:
    def __init__(self, session):
        self.session = session
        self.cached = None
        self.checked = 0
        self.catalog_lock = asyncio.Lock()
        self.update_lock = asyncio.Lock()

    async def latest(self, force=False):
        async with self.catalog_lock:
            if self.cached and not force and time.monotonic()-self.checked < 3600:
                return self.cached
            try:
                async with self.session.get('https://api.github.com/repos/'+REPO+'/releases?per_page=100',
                        headers={'Accept':'application/vnd.github+json','User-Agent':'Pixora-LED-Displays'},
                        timeout=aiohttp.ClientTimeout(total=20),allow_redirects=False) as response:
                    if response.status != 200: raise ValueError('Could not check GitHub for firmware updates. Try again later.')
                    raw = await bounded_body(response,2097152)
                    if len(raw)>2097152: raise ValueError('Firmware update information is too large.')
                import json
                releases = json.loads(raw)
                if not isinstance(releases,list): raise ValueError('Invalid firmware update information.')
                candidates=[]
                for release in releases:
                    if not isinstance(release,dict) or release.get('draft'): continue
                    tag=release.get('tag_name','')
                    match=re.fullmatch(r'led-local-v(\d+\.\d+\.\d+)',tag)
                    if not match: continue
                    number=match[1]
                    name='pixora-v'+number+'-s3-user-ota-firmware.bin'
                    for asset in release.get('assets',[]):
                        digest=asset.get('digest','')
                        if asset.get('name')==name and isinstance(digest,str) and re.fullmatch(r'sha256:[0-9a-f]{64}',digest) and type(asset.get('size')) is int and 1024<=asset['size']<=MAX_SIZE:
                            candidates.append({'version':number,'preview':bool(release.get('prerelease')),
                                'sha256':digest[7:],'size':asset['size'],'url':'https://github.com/'+REPO+'/releases/download/'+tag+'/'+name})
                if not candidates: raise ValueError('No verified S3 firmware release is available.')
                self.cached=max(candidates,key=lambda item:version(item['version']))
                self.checked=time.monotonic()
                return self.cached
            except (aiohttp.ClientError,asyncio.TimeoutError,UnicodeError) as exc:
                raise ValueError('Could not check firmware updates. Local card sending is still available.') from exc

    async def download(self, release):
        url=release['url']
        try:
            for _ in range(5):
                parsed=urlsplit(url)
                if parsed.scheme!='https' or parsed.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com') or parsed.port not in (None,443) or parsed.username or parsed.password:
                    raise ValueError('Untrusted firmware download address.')
                async with self.session.get(url,allow_redirects=False,timeout=aiohttp.ClientTimeout(total=60)) as response:
                    if response.status in (301,302,303,307,308):
                        url=response.headers.get('Location','');continue
                    if response.status!=200: raise ValueError('Could not download the firmware. The panel was not changed.')
                    body=await bounded_body(response,MAX_SIZE)
                    if len(body)!=release['size'] or len(body)>MAX_SIZE or hashlib.sha256(body).hexdigest()!=release['sha256']:
                        raise ValueError('Firmware verification failed. The panel was not changed.')
                    return body
            raise ValueError('Too many firmware download redirects.')
        except (aiohttp.ClientError,asyncio.TimeoutError) as exc:
            raise ValueError('Firmware download failed. The panel was not changed.') from exc
