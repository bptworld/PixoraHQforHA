"""Direct LAN client. Never sends data to Pixora Cloud or retries a write."""
import asyncio
import ipaddress
import re

import aiohttp


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


class DisplayClient:
    def __init__(self, session, host, key=''):
        self.session, self.host, self.key = session, local_host(host), key

    async def request(self, path, payload=None):
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
                    raise ValueError('Display is busy. This card was not accepted.')
                if response.status not in (200, 202):
                    raise ValueError('Display rejected the request (' + str(response.status) + ').')
                try:
                    result = await response.json()
                except (ValueError, UnicodeError) as exc:
                    raise ValueError('The display returned an invalid response. The request was not retried.') from exc
                if not isinstance(result, dict):
                    raise ValueError('The display returned an invalid response.')
                if path in ('/api/message', '/api/frame') and result.get('accepted') is not True:
                    raise ValueError('The display did not confirm this card. Check it before trying again.')
                return result
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ValueError('Could not confirm delivery. Check the display; the request was not retried.') from exc

    async def info(self):
        info = await self.request('/api/info')
        if (not isinstance(info, dict) or not isinstance(info.get('id'), str) or not 1 <= len(info['id']) <= 80
                or not isinstance(info.get('version'), str) or info.get('width') not in (64, 128) or info.get('height') != 32):
            raise ValueError('This display needs Pixora local-display firmware 2.0.14 or newer.')
        version = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', info['version'])
        if not version or tuple(map(int, version.groups())) < (2, 0, 14):
            raise ValueError('This display needs Pixora local-display firmware 2.0.14 or newer.')
        return info

    async def pair(self):
        data = await self.request('/api/pair', {})
        key = data.get('key') if isinstance(data, dict) else None
        if not isinstance(key, str) or len(key) != 32 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('The display returned invalid pairing information.')
        self.key = key

    async def show(self, message, color, duration):
        if type(duration) is not int or not 1 <= duration <= 300:
            raise ValueError('Choose 1 to 300 seconds.')
        if not isinstance(message, str) or not 1 <= len(message) <= 160 or any(ord(c) > 126 or ord(c) < 32 and c != '\n' for c in message):
            raise ValueError('Use 1 to 160 plain-text characters. For other fonts or characters, send an image.')
        if not isinstance(color, (list, tuple)) or len(color) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in color):
            raise ValueError('Choose a valid RGB color.')
        await self.request('/api/message', {'message': message, 'color': ''.join(f'{c:02X}' for c in color), 'duration': duration})

    async def update_firmware(self, body):
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
