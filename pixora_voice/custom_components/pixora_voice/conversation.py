"""Stable Assist conversation bridge. Interpretation runs in the Voice app."""
import json
from pathlib import Path
from homeassistant.components import conversation
from .bridge import converse,origin_area
INTEGRATION_VERSION=json.loads(Path(__file__).with_name('manifest.json').read_text())['version']
async def async_setup_entry(hass,entry,async_add_entities):async_add_entities([LocalVoice(entry)])
class LocalVoice(conversation.ConversationEntity):
    _attr_name='Pixora Voice (Beta)'
    _attr_has_entity_name=True
    _attr_extra_state_attributes={'pixora_voice_version':INTEGRATION_VERSION}
    _attr_supported_features=conversation.ConversationEntityFeature.CONTROL
    def __init__(self,entry):self._attr_unique_id=entry.entry_id
    @property
    def supported_languages(self):return ['en']
    async def _async_handle_message(self,user_input,chat_log):
        speech=await converse(self.hass,user_input,chat_log.conversation_id)
        chat_log.async_add_assistant_content_without_tools(conversation.AssistantContent(agent_id=self.entity_id,content=speech))
        result=conversation.async_get_result_from_chat_log(user_input,chat_log)
        result.continue_conversation=False
        return result
