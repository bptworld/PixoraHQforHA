"""Optional household-key Groq Whisper; native Pixora still handles all text."""
import asyncio
import io
import logging
import wave

from aiohttp import ClientError, ClientTimeout, FormData
from homeassistant.components import stt
from homeassistant.helpers.aiohttp_client import async_get_clientsession



ENDPOINT = 'https://api.groq.com/openai/v1/audio/transcriptions'
MAX_AUDIO = 30 * 16000 * 2
_LOGGER = logging.getLogger(__name__)
ERRORS = {
    401: 'Groq rejected the API key. Update it in Pixora Voice.',
    403: 'Groq denied access. Check the key and model permissions.',
    413: 'Groq rejected the audio size.',
    429: 'Groq free-plan or rate limit reached. No automatic retry.',
}


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([GroqWhisper(entry.entry_id)])


def wav_audio(pcm):
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(pcm)
    return output.getvalue()


class GroqWhisper(stt.SpeechToTextEntity):
    _attr_name = 'Pixora Groq Whisper'
    _attr_should_poll = False

    def __init__(self, entry_id):
        self._attr_unique_id = entry_id + '-groq-whisper'

    @property
    def supported_languages(self): return ['en']
    @property
    def supported_formats(self): return [stt.AudioFormats.WAV]
    @property
    def supported_codecs(self): return [stt.AudioCodecs.PCM]
    @property
    def supported_bit_rates(self): return [stt.AudioBitRates.BITRATE_16]
    @property
    def supported_sample_rates(self): return [stt.AudioSampleRates.SAMPLERATE_16000]
    @property
    def supported_channels(self): return [stt.AudioChannels.CHANNEL_MONO]

    async def async_process_audio_stream(self, metadata, stream):
        from .bridge import transport
        audio=bytearray()
        failed=stt.SpeechResult(None,stt.SpeechResultState.ERROR)
        try:
            async with asyncio.timeout(40):
                async for chunk in stream:
                    if len(audio)+len(chunk)>MAX_AUDIO:return failed
                    audio.extend(chunk)
            if not audio or len(audio)%2:return failed
            result=await transport(self.hass,'speech',audio=bytes(audio))
            text=result.get('text')
            return stt.SpeechResult(text,stt.SpeechResultState.SUCCESS) if isinstance(text,str) and 0<len(text)<=2000 else failed
        except (OSError,ValueError,KeyError,TypeError,ClientError,asyncio.TimeoutError):
            _LOGGER.warning('Voice app speech could not be confirmed. No automatic retry or command sent.')
            return failed
        finally:audio.clear()
