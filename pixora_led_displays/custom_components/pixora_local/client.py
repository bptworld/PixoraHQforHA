"""Direct LAN client. Never sends data to Pixora Cloud or retries a write."""
import asyncio
import ipaddress
import re
import weakref
from contextlib import asynccontextmanager

import aiohttp

_connections = weakref.WeakKeyDictionary()

@asynccontextmanager
async def display_connection(session, host):
    """One app connection per panel; an OTA owns it through restart verification."""
    hosts = _connections.setdefault(session, {})
    connection = hosts.setdefault(host, {'lock': asyncio.Lock(), 'owner': None})
    task = asyncio.current_task()
    if connection['owner'] is task:
        yield
        return
    async with connection['lock']:
        connection['owner'] = task
        try:
            yield
        finally:
            connection['owner'] = None


def local_host(value):
    if not isinstance(value, str):
        raise ValueError("Enter the display's local IPv4 address.")
    try:
        address = ipaddress.IPv4Address(value.strip())
    except ipaddress.AddressValueError as exc:
        raise ValueError("Enter the display's local IPv4 address.") from exc
    host = str(address)
    if not any(address in ipaddress.IPv4Network(network) for network in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('Enter the display\'s local IPv4 address.')
    return host


class DisplayBusy(ValueError):
    """Panel explicitly rejected this write before accepting it."""


class DisplayUnavailable(ValueError):
    """A read-only status request failed at the transport layer."""


class DisplayWriteUnconfirmed(ValueError):
    """Transport failed after a write; read state before any further action."""


class PriorityMessageActive(ValueError):
    """A deck frame was explicitly rejected because an HA message has priority."""


class DisplayClient:
    def __init__(self, session, host, key=''):
        self.session, self.host, self.key = session, local_host(host), key

    async def request(self, path, payload=None):
        async with display_connection(self.session, self.host):
            return await self._request(path, payload)

    async def _request(self, path, payload=None):
        headers = {'Authorization': 'Bearer ' + self.key} if self.key else {}
        try:
            async with self.session.request(
                'GET' if payload is None else 'POST', 'http://' + self.host + path,
                json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=False,
            ) as response:
                if response.status == 403:
                    raise ValueError('Restart the display, then connect within two minutes.')
                if response.status == 401:
                    raise ValueError('Display authorization failed. Use Reconfigure in the integration to reconnect it.')
                if response.status == 409:
                    try:
                        detail=await response.json()
                    except (ValueError,aiohttp.ClientError):detail={}
                    if isinstance(detail,dict) and detail.get('error')=='priority_message_active':
                        raise PriorityMessageActive('An HA message has priority.')
                    raise DisplayBusy('Display is busy. This card was not accepted.')
                if response.status not in (200, 202):
                    raise ValueError('Display rejected the request (' + str(response.status) + ').')
                try:
                    result = await response.json()
                except (ValueError, UnicodeError) as exc:
                    raise ValueError('The display returned an invalid response. The request was not retried.') from exc
                if not isinstance(result, dict):
                    raise ValueError('The display returned an invalid response.')
                if path in ('/api/message', '/api/frame', '/api/settings', '/api/reboot') and result.get('accepted') is not True:
                    raise ValueError('The display did not confirm this card. Check it before trying again.')
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if payload is None:
                raise DisplayUnavailable('The display at '+self.host+' did not answer the status check. Check its power and current IP address.') from exc
            raise DisplayWriteUnconfirmed('Could not confirm delivery. Check the display; the request was not retried.') from exc

    async def info(self):
        for attempt in range(3):
            try:
                info = await self.request('/api/info')
                break
            except DisplayUnavailable:
                if attempt == 2: raise
                await asyncio.sleep(1)
        if (not isinstance(info, dict) or not isinstance(info.get('id'), str) or not 1 <= len(info['id']) <= 80
                or not isinstance(info.get('version'), str) or info.get('width') not in (64, 128) or info.get('height') != 32):
            raise ValueError('This display needs Pixora local-display firmware 2.0.14 or newer.')
        version = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', info['version'])
        if not version or tuple(map(int, version.groups())) < (2, 0, 14):
            raise ValueError('This display needs Pixora local-display firmware 2.0.14 or newer.')
        if 'bootId' in info and (not isinstance(info['bootId'],str) or not re.fullmatch(r'[0-9a-f]{16}',info['bootId'])):
            raise ValueError('The display returned an invalid startup identifier.')
        return info

    async def pair(self):
        data = await self.request('/api/pair', {})
        key = data.get('key') if isinstance(data, dict) else None
        if not isinstance(key, str) or len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('The display returned invalid pairing information.')
        self.key = key

    async def hub_action(self,payload):
        try:
            async with self.session.post(self.app_host+'/api/studio/ha-action',json={'id':self.device_id,**payload},
                    headers={'Authorization':'Bearer '+self.key},allow_redirects=False,timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status!=200:raise ValueError('The hub did not accept this display action. It was not retried.')
                result=await response.json()
                if result.get('accepted') is not True:raise ValueError('The hub did not confirm this display action.')
        except (aiohttp.ClientError,asyncio.TimeoutError) as exc:
            raise ValueError('Hub action outcome is uncertain. Check LED Studio; it was not retried.') from exc

    async def show(self, message, color, duration):
        if type(duration) is not int or not 1 <= duration <= 300:
            raise ValueError('Choose 1 to 300 seconds.')
        if not isinstance(message, str) or not 1 <= len(message) <= 160 or any(ord(c) > 126 or ord(c) < 32 and c != '\n' for c in message):
            raise ValueError('Use 1 to 160 plain-text characters. For other fonts or characters, send an image.')
        if not isinstance(color, (list, tuple)) or len(color) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in color):
            raise ValueError('Choose a valid RGB color.')
        if getattr(self,'app_host',''):
            return await self.hub_action({'action':'message','message':message,'color':list(color),'duration':duration})
        await self.request('/api/message', {'message': message, 'color': ''.join(f'{c:02X}' for c in color), 'duration': duration})

    async def update_firmware(self, body):
        async with display_connection(self.session, self.host):
            return await self._update_firmware(body)

    async def _update_firmware(self, body):
        if not 1024 <= len(body) <= 2097152 or body[0] != 0xe9 or body[12:14] != b'\x09\x00' or body[32:36] != b'\x32\x54\xcd\xab':
            raise ValueError('Choose MatrixPortal S3 user-OTA firmware, not a factory image.')
        try:
            async with self.session.post('http://' + self.host + '/api/update', data=body,
                    headers={'Authorization': 'Bearer ' + self.key, 'Content-Type': 'application/octet-stream'},
                    timeout=aiohttp.ClientTimeout(total=95), allow_redirects=False) as response:
                if response.status != 200:
                    raise ValueError('The panel did not confirm the update. Check it before trying again.')
                result = await response.json()
                if not isinstance(result, dict) or result.get('updated') is not True:
                    raise ValueError('The panel did not confirm the update. Check it before trying again.')
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ValueError('Update outcome is uncertain. Check the panel; it was not retried.') from exc
