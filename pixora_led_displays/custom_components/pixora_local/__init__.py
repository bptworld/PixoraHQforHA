"""Home Assistant actions for Pixora panels, with no Cloud dependency."""
import base64
from pathlib import Path
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr
from .client import DisplayClient

DOMAIN = 'pixora_local'


def rgb(value):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in value):
        raise vol.Invalid('Choose three RGB color values from 0 to 255.')
    return list(value)



async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})

    async def show_card(call):
        client = hass.data[DOMAIN].get(call.data['config_entry_id'])
        if client is None:
            raise HomeAssistantError('Select a connected Pixora display.')
        try:
            if call.service == 'show_image':
                info = await client.info()
                def image_pixels():
                    path = str(Path(call.data['image_path']).resolve())
                    if not hass.config.is_allowed_path(path):
                        raise ValueError('Use an image inside an allowed media directory, such as /config/www.')
                    from PIL import Image, ImageOps
                    if Path(path).stat().st_size > 5 * 1024 * 1024:
                        raise ValueError('Use an image smaller than 5 MB.')
                    with Image.open(path) as image:
                        if image.width * image.height > 16000000:
                            raise ValueError('Use an image with at most 16 million pixels.')
                        image = ImageOps.exif_transpose(image).convert('RGBA')
                        image = Image.alpha_composite(Image.new('RGBA', image.size, 'black'), image).convert('RGB')
                        return base64.b64encode(ImageOps.pad(image, (info['width'], info['height']), color='black').tobytes()).decode('ascii')
                pixels = await hass.async_add_executor_job(image_pixels)
                await client.request('/api/frame', {'rgb': pixels, 'width': info['width'], 'height': info['height'], 'duration': call.data['duration']})
            else:
                await client.show(call.data['message'], call.data['color'], call.data['duration'])
        except (ValueError, OSError) as exc:
            raise HomeAssistantError(str(exc)) from exc

    common = {vol.Required('config_entry_id'): str, vol.Optional('duration', default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=300))}
    hass.services.async_register(DOMAIN, 'show_card', show_card, schema=vol.Schema({**common, vol.Required('message'): str, vol.Optional('color', default=[255, 255, 255]): rgb}))
    hass.services.async_register(DOMAIN, 'show_image', show_card, schema=vol.Schema({**common, vol.Required('image_path'): str}))
    return True


async def async_setup_entry(hass, entry):
    client = DisplayClient(async_get_clientsession(hass), entry.data['host'], entry.data['key'])
    # Setup does not send a card or require Cloud connectivity.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
    dr.async_get(hass).async_get_or_create(config_entry_id=entry.entry_id, identifiers={(DOMAIN, entry.data['device_id'])}, manufacturer='Pixora', name=entry.title, model='MatrixPortal S3 LED display')
    await hass.config_entries.async_forward_entry_setups(entry, ['notify'])
    return True


async def async_unload_entry(hass, entry):
    unloaded = await hass.config_entries.async_unload_platforms(entry, ['notify'])
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
