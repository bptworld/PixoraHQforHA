"""Pair an LED display on the same LAN from Home Assistant's UI."""
from pathlib import Path
import re
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .client import DisplayClient

DOMAIN = 'pixora_local'


class PixoraLocalFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                client = DisplayClient(async_get_clientsession(self.hass), user_input['host'])
                info = await client.info()
                await self.async_set_unique_id(info['id'])
                self._abort_if_unique_id_configured()
                await client.pair()
            except ValueError as exc:
                errors['base'] = 'cannot_connect'
                self._reason = str(exc)
            else:
                return self.async_create_entry(title=info.get('name') or 'Pixora LED', data={'host': client.host, 'key': client.key, 'device_id': info['id']})
        return self.async_show_form(step_id='user', data_schema=vol.Schema({vol.Required('host'): str}), errors=errors,
                                    description_placeholders={'reason': getattr(self, '_reason', '')})

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            try:
                client = DisplayClient(async_get_clientsession(self.hass), user_input['host'], entry.data['key'])
                info = await client.info()
                if info['id'] != entry.data['device_id']:
                    raise ValueError('This is a different panel. Enter the address of this display.')
                await client.pair()
            except ValueError as exc:
                errors['base'] = 'cannot_connect'
                self._reason = str(exc)
            else:
                return self.async_update_reload_and_abort(entry, data_updates={'host': client.host, 'key': client.key})
        return self.async_show_form(step_id='reconfigure', data_schema=vol.Schema({vol.Required('host', default=entry.data['host']): str}), errors=errors,
                                    description_placeholders={'reason': getattr(self, '_reason', '')})

    async def async_step_hassio(self, discovery_info):
        """The app already paired these panels; do not ask users to pair twice."""
        displays = discovery_info.config.get('displays', [])
        if not isinstance(displays, list) or len(displays) > 30:
            return self.async_abort(reason='invalid_discovery')
        for display in displays:
            await self.hass.config_entries.flow.async_init(
                DOMAIN, context={'source': 'integration_discovery'}, data=display)
        marker = Path(self.hass.config.path('.pixora-led-ha-version'))
        await self.hass.async_add_executor_job(marker.write_text, '1.0.5')
        return self.async_abort(reason='panels_registered')

    async def async_step_integration_discovery(self, display):
        if not isinstance(display, dict):
            return self.async_abort(reason='invalid_discovery')
        try:
            ident, key = display['id'], display['key']
            if not isinstance(ident, str) or not 1 <= len(ident) <= 80 or not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key):
                raise ValueError('Invalid panel identity')
            client = DisplayClient(async_get_clientsession(self.hass), display['host'], key)
        except (KeyError, ValueError):
            return self.async_abort(reason='invalid_discovery')
        await self.async_set_unique_id(ident)
        data = {'host':client.host, 'key':key, 'device_id':ident}
        existing = next((entry for entry in self.hass.config_entries.async_entries(DOMAIN) if entry.unique_id == ident), None)
        if existing:
            if existing.source != 'ignore' and any(existing.data.get(k) != v for k,v in data.items()):
                self.hass.config_entries.async_update_entry(existing, data={**existing.data, **data})
                await self.hass.config_entries.async_reload(existing.entry_id)
            return self.async_abort(reason='already_configured')
        self._abort_if_unique_id_configured()
        name = display.get('name')
        return self.async_create_entry(title=name[:80] if isinstance(name, str) and name else 'Pixora LED', data=data)
