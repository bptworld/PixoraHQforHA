"""Native Assist entry point for the local Pixora Voice app."""
from homeassistant.const import Platform

async def async_setup_entry(hass,entry):
    from .planner import install_reply_service
    install_reply_service(hass)
    from .flows import install_services
    install_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry,[Platform.CONVERSATION])
    return True

async def async_unload_entry(hass,entry):
    unloaded=await hass.config_entries.async_unload_platforms(entry,[Platform.CONVERSATION])
    if unloaded:
        for future in hass.data.get('pixora_voice',{}).get('planner_pending',{}).values():
            if not future.done():future.cancel()
        for future in hass.data.get('pixora_voice',{}).get('flow_pending',{}).values():
            if not future.done():future.cancel()
        for service in ('planner_reply','planner_vocabulary','flow_reply','flow_vocabulary','refresh_flow_phrases','speech_ready'):hass.services.async_remove('pixora_voice',service)
    return unloaded
