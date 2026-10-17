"""Native HA notify entities, one per locally paired LED panel."""
from homeassistant.components.notify import NotifyEntity
from homeassistant.exceptions import HomeAssistantError
from . import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([PixoraDisplay(hass.data[DOMAIN][entry.entry_id], entry)])


class PixoraDisplay(NotifyEntity):
    _attr_has_entity_name = True
    _attr_name = 'Display'
    _attr_icon = 'mdi:led-on'
    _attr_should_poll = False

    def __init__(self, client, entry):
        self._client = client
        self._attr_unique_id = entry.data['device_id'] + '_display'
        self._attr_device_info = {'identifiers': {(DOMAIN, entry.data['device_id'])},
                                  'manufacturer': 'Pixora', 'name': entry.title,
                                  'model': 'MatrixPortal S3 LED display'}

    async def async_send_message(self, message, title=None):
        try:
            await self._client.show(message, [255, 255, 255], 10)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc
