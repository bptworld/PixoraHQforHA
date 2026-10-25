"""Optional Groq boundary: per-hub secrets, bounded audio, exact text, no retry."""
import asyncio
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'pixora_voice'
sys.path.insert(0,str(ROOT))
from speech_settings import read_settings,save_settings,public_settings


class SettingsTests(unittest.TestCase):
    def test_retire_only_owned_phrases_and_keep_verified_recovery(self):
        from planner_phrases import MARKER,retire_phrase_files
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);active=root/'active';active.mkdir();recovery=root/'recovery'
            own=active/'pixora_voice_flows.yaml';own.write_text(MARKER+'{}')
            foreign=active/'pixora_voice_planner.yaml';foreign.write_text('user edited sentences')
            unrelated=active/'sentences.yaml';unrelated.write_text('my sentences')
            self.assertEqual(retire_phrase_files(active,recovery),['pixora_voice_flows.yaml'])
            self.assertFalse(own.exists());self.assertEqual(foreign.read_text(),'user edited sentences')
            self.assertEqual(unrelated.read_text(),'my sentences')
            self.assertEqual(next(recovery.glob('*/pixora_voice_flows.yaml')).read_text(),MARKER+'{}')
            self.assertEqual(retire_phrase_files(active,recovery),[])

    def test_key_is_per_hub_preserved_when_blank_and_never_returned(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            key='gsk_'+'fake_for_test_'*3
            public=save_settings(a,{'enabled':True,'key':key})
            self.assertNotIn(key,json.dumps(public));self.assertTrue(public['key_saved'])
            save_settings(a,{'enabled':False,'key':''})
            self.assertEqual(read_settings(a)['key'],key)
            self.assertFalse(read_settings(b)['enabled']);self.assertFalse(read_settings(b)['key'])
            save_settings(a,{'enabled':False,'clear_key':True})
            self.assertFalse(public_settings(read_settings(a))['key_saved'])
            with self.assertRaises(ValueError):save_settings(a,{'enabled':True})


class SpeechTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        def module(name,**attrs):
            m=types.ModuleType(name);m.__dict__.update(attrs);return m
        enums={'AudioFormats':NS(WAV='wav'),'AudioCodecs':NS(PCM='pcm'),
               'AudioBitRates':NS(BITRATE_16=16),'AudioSampleRates':NS(SAMPLERATE_16000=16000),
               'AudioChannels':NS(CHANNEL_MONO=1),'SpeechResultState':NS(ERROR='error',SUCCESS='success'),
               'SpeechResult':lambda text,state:NS(text=text,state=state),'SpeechToTextEntity':object}
        self.calls=[];self.status=200;self.response={'text':'What is the heat set to?'}
        owner=self
        class Response:
            @property
            def status(self):return owner.status
            @property
            def content(self):return self
            async def iter_chunked(self,n):
                raw=json.dumps(owner.response).encode()
                yield raw[:4];yield raw[4:]
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
        def post(*args,**kwargs):
            self.calls.append((args,kwargs));return Response()
        self.modules={'homeassistant':module('homeassistant'), 'homeassistant.components':module('homeassistant.components'), 'homeassistant.helpers':module('homeassistant.helpers'),
             'homeassistant.components.stt':module('homeassistant.components.stt',**enums),
             'homeassistant.helpers.aiohttp_client':module('homeassistant.helpers.aiohttp_client',async_get_clientsession=lambda h:NS(post=post)),
             'custom_components.pixora_voice.speech_settings':sys.modules['speech_settings']}
        self.parent=self.modules['homeassistant.components']
        self.patch=patch.dict(sys.modules,self.modules);self.patch.start()
        self.attr=patch.object(self.parent,'stt',self.modules['homeassistant.components.stt'],create=True);self.attr.start()
        spec=importlib.util.spec_from_file_location('custom_components.pixora_voice.groq_test_stt',ROOT/'custom_components/pixora_voice/stt.py')
        self.stt=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.stt)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.addCleanup(self.patch.stop);self.addCleanup(self.attr.stop)
        self.provider=self.stt.GroqWhisper('test')
        self.provider.hass=NS(config=NS(path=lambda:self.tmp.name))
        save_settings(self.tmp.name,{'enabled':True,'key':'gsk_'+'fake_for_test_'*3})

    async def audio(self,chunks=None):
        for chunk in chunks or [b'\x00\x00'*16000]:yield chunk

    async def test_exact_text_and_wav_format(self):
        result=await self.provider.async_process_audio_stream(None,self.audio())
        self.assertEqual(result.text,'What is the heat set to?');self.assertEqual(result.state,'success')
        self.assertEqual(len(self.calls),1)
        url=self.calls[0][0][0];kw=self.calls[0][1]
        self.assertEqual(url,'https://api.groq.com/openai/v1/audio/transcriptions')
        self.assertFalse(kw['allow_redirects'])
        with wave.open(io.BytesIO(self.stt.wav_audio(b'\0\0'*100)),'rb') as wav:
            self.assertEqual((wav.getnchannels(),wav.getsampwidth(),wav.getframerate()),(1,2,16000))

    async def test_disabled_and_oversize_never_upload(self):
        save_settings(self.tmp.name,{'enabled':False})
        self.assertEqual((await self.provider.async_process_audio_stream(None,self.audio())).state,'error')
        self.assertFalse(self.calls)
        save_settings(self.tmp.name,{'enabled':True})
        self.assertEqual((await self.provider.async_process_audio_stream(None,self.audio([b'\0'*(self.stt.MAX_AUDIO+2)]))).state,'error')
        self.assertFalse(self.calls)

    async def test_failed_service_never_retries(self):
        for status in [401,403,429,503,302]:
            self.status=status;self.calls.clear()
            result=await self.provider.async_process_audio_stream(None,self.audio())
            self.assertEqual(result.state,'error');self.assertEqual(len(self.calls),1)

    async def test_empty_or_oversized_text_never_reaches_handler(self):
        for text in ['', 'a'*2001]:
            self.response={'text':text}
            self.assertEqual((await self.provider.async_process_audio_stream(None,self.audio())).state,'error')
