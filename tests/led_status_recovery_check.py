"""Only transient read failures may be retried; writes and invalid replies may not."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays/custom_components/pixora_local'))
from client import DisplayClient, DisplayUnavailable

async def check():
    client=DisplayClient(None,'192.168.4.91')
    info={'id':'center','version':'2.0.21','width':128,'height':32}
    with patch('client.asyncio.sleep',AsyncMock()) as sleep:
        client.request=AsyncMock(side_effect=[DisplayUnavailable('missed read'),info])
        assert await client.info()==info
        assert client.request.await_count==2 and sleep.await_count==1
        assert all(call.args==('/api/info',) for call in client.request.await_args_list)
        client.request=AsyncMock(side_effect=DisplayUnavailable('offline'))
        try:await client.info()
        except DisplayUnavailable:pass
        else:raise AssertionError('Offline status accepted')
        assert client.request.await_count==3
        client.request=AsyncMock(side_effect=ValueError('authorization failed'))
        try:await client.info()
        except ValueError:pass
        else:raise AssertionError('Invalid status accepted')
        assert client.request.await_count==1
        client.request=AsyncMock(side_effect=ValueError('uncertain write'))
        try:await client.show('Test',[255,255,255],1)
        except ValueError:pass
        else:raise AssertionError('Unconfirmed write accepted')
        assert client.request.await_count==1

asyncio.run(check())
print('Status recovery passed: read-only recovery, bounded offline checks, invalid reply isolation and one-shot writes.')
