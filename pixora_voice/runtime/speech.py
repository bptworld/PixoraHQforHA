"""Optional Groq transcription executed by the app, with bounded audio and no retries."""
import asyncio,io,json,logging,wave
from aiohttp import ClientError,ClientTimeout,FormData
from speech_settings import read_settings,record_usage
MAX_AUDIO=30*16000*2
ENDPOINT='https://api.groq.com/openai/v1/audio/transcriptions'
_LOGGER=logging.getLogger(__name__)
def wav_audio(pcm):
    output=io.BytesIO()
    with wave.open(output,'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(pcm)
    return output.getvalue()
async def transcribe(session,config_root,audio,timezone='UTC'):
    attempted=successful=False;status=None;headers={};settings={};seconds=0
    try:
        if not audio or len(audio)>MAX_AUDIO or len(audio)%2:return {'text':None}
        settings=await asyncio.to_thread(read_settings,config_root)
        if settings.get('enabled') is not True or not settings.get('key'):return {'text':None}
        form=FormData();seconds=len(audio)/32000
        form.add_field('file',wav_audio(audio),filename='speech.wav',content_type='audio/wav')
        for key,value in {'model':'whisper-large-v3-turbo','language':'en','response_format':'json','temperature':'0'}.items():form.add_field(key,value)
        attempted=True
        async with session.post(ENDPOINT,data=form,headers={'Authorization':'Bearer '+settings['key']},timeout=ClientTimeout(total=25),allow_redirects=False) as response:
            status=response.status;headers=response.headers
            if status!=200:
                _LOGGER.warning('Groq transcription failed (HTTP %s). No automatic retry or command sent.',status)
                return {'text':None}
            raw=bytearray()
            async for chunk in response.content.iter_chunked(4096):
                if len(raw)+len(chunk)>16000:raise ValueError('Oversized speech response')
                raw.extend(chunk)
            result=json.loads(raw);text=result.get('text') if isinstance(result,dict) else None
            if not isinstance(text,str) or not text.strip() or len(text)>2000:return {'text':None}
            successful=True
            return {'text':text.strip()}
    except (OSError,ValueError,TypeError,ClientError,asyncio.TimeoutError):
        _LOGGER.warning('Groq transcription could not be confirmed. No automatic retry or command sent.')
        return {'text':None}
    finally:
        if attempted:
            try:await asyncio.to_thread(record_usage,config_root,settings['key'],seconds,status,successful,headers,timezone)
            except (OSError,ValueError,TypeError):_LOGGER.warning('Speech usage could not be saved.')
