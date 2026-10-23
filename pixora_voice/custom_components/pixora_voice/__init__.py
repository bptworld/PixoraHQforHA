"""Native Assist entry point for the local Pixora Voice app."""
from homeassistant.const import Platform

async def async_setup_entry(hass,entry):
    await hass.config_entries.async_forward_entry_setups(entry,[Platform.CONVERSATION])
    return True

async def async_unload_entry(hass,entry):
    return await hass.config_entries.async_unload_platforms(entry,[Platform.CONVERSATION])
