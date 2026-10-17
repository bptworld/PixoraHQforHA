"""Pair an LED display on the same LAN from Home Assistant's UI."""
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
