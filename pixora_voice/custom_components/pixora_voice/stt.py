"""Optional household-key Groq Whisper; native Pixora still handles all text."""
import asyncio
import io
import logging
import wave

from aiohttp import ClientError, ClientTimeout, FormData
from homeassistant.components import stt
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .speech_settings import read_settings

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
        audio = bytearray()
        failed = stt.SpeechResult(None, stt.SpeechResultState.ERROR)
        try:
            settings = await asyncio.to_thread(read_settings, self.hass.config.path())
            if settings.get('enabled') is not True or not settings.get('key'):
                _LOGGER.warning('Groq speech is disabled or missing its key. No audio sent.')
                return failed
            async with asyncio.timeout(40):
                async for chunk in stream:
                    if len(audio) + len(chunk) > MAX_AUDIO:
                        _LOGGER.warning('Groq speech exceeded the 30-second audio limit. No audio sent.')
                        return failed
                    audio.extend(chunk)
            if not audio or len(audio) % 2:
                _LOGGER.warning('Groq speech received empty or invalid PCM audio. No audio sent.')
                return failed
            form = FormData()
            form.add_field('file', wav_audio(audio), filename='speech.wav', content_type='audio/wav')
            audio.clear()
            form.add_field('model', 'whisper-large-v3-turbo')
            form.add_field('language', 'en')
            form.add_field('response_format', 'json')
            form.add_field('temperature', '0')
            session = async_get_clientsession(self.hass)
            async with session.post(ENDPOINT, data=form,
                    headers={'Authorization': 'Bearer ' + settings['key']},
                    timeout=ClientTimeout(total=25), allow_redirects=False) as response:
                if response.status != 200:
                    _LOGGER.warning('Groq speech failed (HTTP %s): %s No command sent.',
                                    response.status, ERRORS.get(response.status, 'Speech service unavailable. No automatic retry.'))
                    return failed
                raw = bytearray()
                async for chunk in response.content.iter_chunked(4096):
                    if len(raw) + len(chunk) > 16000:
                        raise ValueError('Oversized speech response')
                    raw.extend(chunk)
                import json
                result = json.loads(raw)
                text = result.get('text') if isinstance(result, dict) else None
                if not isinstance(text, str) or not text.strip() or len(text) > 2000:
                    _LOGGER.warning('Groq speech returned no usable text. No command sent.')
                    return failed
                return stt.SpeechResult(text.strip(), stt.SpeechResultState.SUCCESS)
        except (OSError, ValueError, TypeError, ClientError, asyncio.TimeoutError):
            _LOGGER.warning('Groq speech connection, timeout or configuration failure. Check internet and the saved key. No automatic retry or command sent.')
            return failed
        finally:
            audio.clear()
