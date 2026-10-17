"""Exercise companion HA callbacks with a small HA API harness, not a running HA hub."""
import asyncio
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'pixora_led_displays/custom_components'))
for name in ('homeassistant', 'homeassistant.helpers', 'homeassistant.helpers.aiohttp_client', 'homeassistant.helpers.device_registry', 'homeassistant.exceptions', 'homeassistant.config_entries', 'homeassistant.components', 'homeassistant.components.notify'):
    sys.modules[name] = types.ModuleType(name)
class HAError(Exception): pass
sys.modules['homeassistant.exceptions'].HomeAssistantError = HAError
sys.modules['homeassistant.exceptions'].ConfigEntryNotReady = HAError
sys.modules['homeassistant.helpers.aiohttp_client'].async_get_clientsession = lambda hass: None
class Flow:
    def __init_subclass__(cls, **kwargs): pass
    def async_show_form(self, **kwargs): return kwargs
    def _get_reconfigure_entry(self): return self.entry
    def async_update_reload_and_abort(self, entry, **kwargs): return {'entry':entry, **kwargs}
sys.modules['homeassistant.config_entries'].ConfigFlow = Flow
sys.modules['homeassistant.components.notify'].NotifyEntity = object
integration = importlib.import_module('pixora_local')
flow_module = importlib.import_module('pixora_local.config_flow')
notify_module = importlib.import_module('pixora_local.notify')

async def check():
    callbacks = {}
    class Services:
        def async_register(self, domain, name, callback, schema): callbacks[name] = (callback, schema)
    panel = types.SimpleNamespace(show=AsyncMock(), request=AsyncMock(), info=AsyncMock(return_value={'id':'stable','width':64,'height':32}))
    hass = types.SimpleNamespace(data={'pixora_local': {'entry1':panel}}, services=Services())
    await integration.async_setup(hass, {})
    callback,schema = callbacks['show_card']
    data=schema({'config_entry_id':'entry1','message':'Washer finished'})
    await callback(types.SimpleNamespace(data=data, service='show_card'))
    panel.show.assert_awaited_once_with('Washer finished',[255,255,255],10)
    panel.show.side_effect=ValueError('Uncertain; not retried')
    try: await callback(types.SimpleNamespace(data=data,service='show_card'))
    except HAError: pass
    else: raise AssertionError('HA swallowed delivery failure')
    assert panel.show.await_count==2
    try: await callback(types.SimpleNamespace(data={**data,'config_entry_id':'missing'},service='show_card'))
    except HAError: pass
    else: raise AssertionError('Missing display accepted')
    entry=types.SimpleNamespace(data={'host':'192.168.1.50','key':'a'*32,'device_id':'stable'},title='Kitchen',entry_id='entry1')
    class Client:
        def __init__(self, session,host,key=''): self.host,self.key=host,key
        async def info(self): return {'id':ident}
        async def pair(self): pass
    flow_module.DisplayClient=Client
    flow=flow_module.PixoraLocalFlow();flow.hass=hass;flow.entry=entry
    ident='stable'
    result=await flow.async_step_reconfigure({'host':'192.168.1.60'})
    assert result['entry'] is entry and result['data_updates']=={'host':'192.168.1.60','key':'a'*32}
    ident='another-panel'
    result=await flow.async_step_reconfigure({'host':'192.168.1.61'})
    assert result['errors']['base']=='cannot_connect'
    entity=notify_module.PixoraDisplay(panel,entry)
    try: await entity.async_send_message('Done')
    except HAError: pass
    else: raise AssertionError('Notify swallowed delivery failure')
    assert entity.unique_id=='stable_display' if hasattr(entity,'unique_id') else entity._attr_unique_id=='stable_display'

asyncio.run(check())
print('HA callback checks passed: schemas, defaults, notify, errors without retry, stable reconfiguration and wrong-panel rejection.')
