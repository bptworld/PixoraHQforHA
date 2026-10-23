"""One local agent; no accounts, tokens or cloud setup."""
from homeassistant import config_entries

class VoiceConfigFlow(config_entries.ConfigFlow,domain='pixora_voice'):
    VERSION=1

    async def async_step_user(self,user_input=None):
        await self.async_set_unique_id('pixora_voice_local')
        self._abort_if_unique_id_configured()
        if user_input is not None:return self.async_create_entry(title='Pixora Voice',data={})
        return self.async_show_form(step_id='user')
