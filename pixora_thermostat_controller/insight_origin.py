"""Shared source for bounded, optional origin reporting in standalone app packages.

Copies ship inside each app's Docker build context; keep them byte-identical.
"""
import asyncio
import logging
import os
import re


def warn(message):
    try:logging.getLogger('pixora.insight').warning(message)
    except Exception:pass


class OriginReporter:
    def __init__(self, send, source):
        self.send, self.source = send, source
        self.queue = asyncio.Queue(maxsize=32)
        self.task = None
        self.closed = False

    def emit(self, entities, reason, context=None, operation=None, target=None):
        if self.closed:return
        try:
            ids = [v for v in entities[:128] if isinstance(v, str) and re.fullmatch(r'[a-z_]+\.[a-z0-9_]+', v)]
            report = {'source': self.source, 'entity_id': ids, 'reason': str(reason)[:600], 'outcome': 'requested'}
            if isinstance(context, str) and re.fullmatch(r'[A-Za-z0-9_-]{16,80}', context):report['action_context'] = context
            if isinstance(operation, str):report['operation'] = operation[:100]
            if isinstance(target, str):report['target_name'] = target[:120]
            if self.queue.full():
                warn('Origin queue full; device command unchanged.')
                return
            self.queue.put_nowait((asyncio.get_running_loop().time(), report))
            if self.task is None or self.task.done():self.task = asyncio.create_task(self.run())
        except Exception:
            warn('Origin unavailable; device command unchanged.')

    async def run(self):
        while True:
            at, report = await self.queue.get()
            if asyncio.get_running_loop().time()-at > 30:continue
            try:await asyncio.wait_for(self.send(report), 2)
            except Exception:warn('Origin report unconfirmed; not retried.')

    async def close(self):
        self.closed = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


def ha_reporter(session, source):
    async def send(report):
        token = os.environ.get('SUPERVISOR_TOKEN', '')
        if not token:raise ValueError('No local HA API access')
        async with session.post('http://supervisor/core/api/events/pixora_insight', json=report,
                headers={'Authorization': 'Bearer '+token}, allow_redirects=False) as response:
            if response.status != 200:raise ValueError('Origin not confirmed')
    return OriginReporter(send, source)
