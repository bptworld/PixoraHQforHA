"""Hub-owned optional speech credentials. Never return the key to the browser."""
import json
import re
import hashlib
import threading
from datetime import datetime,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
from pathlib import Path
from planner_phrases import write_owned

SETTINGS = 'pixora_voice_speech.json'
STATS = 'pixora_voice_speech_stats.json'
STATS_LOCK = threading.Lock()


def _day(zone):
    try:return datetime.now(ZoneInfo(zone)).date().isoformat()
    except (ZoneInfoNotFoundError,ValueError,TypeError):return datetime.now(timezone.utc).date().isoformat()


def read_stats(config_root,key=''):
    path=Path(config_root)/'.storage'/STATS
    try:
        value=json.loads(path.read_text()) if not path.is_symlink() else {}
    except (OSError,ValueError):value={}
    if not isinstance(value,dict):value={}
    zone=value.get('timezone','UTC')
    if not isinstance(zone,str) or len(zone)>80:zone='UTC'
    day=_day(zone)
    if value.get('key_id')!=hashlib.sha256(key.encode()).hexdigest() or value.get('day')!=day:value={}
    result={'day':day,'timezone':zone,'requests':0,'successful':0,'failed':0,'audio_seconds':0,'last_status':None,'updated_at':None,'quota':{}}
    for field in ('requests','successful','failed','audio_seconds'):
        v=value.get(field)
        if type(v) in (int,float) and 0<=v<=1e10:result[field]=v
    status=value.get('last_status')
    if type(status) is int and 100<=status<=599:result['last_status']=status
    stamp=value.get('updated_at')
    if isinstance(stamp,str) and re.fullmatch(r'[0-9T:.+Z-]{10,40}',stamp):result['updated_at']=stamp
    quota=value.get('quota',{})
    if isinstance(quota,dict):
        for name in ('limit_requests','remaining_requests','reset_requests','retry_after','limit_audio_seconds','remaining_audio_seconds','reset_audio_seconds'):
            v=quota.get(name)
            if isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9 .:+-]{1,60}',v):result['quota'][name]=v
    return result


def record_usage(config_root,key,seconds,status,successful,headers,zone='UTC'):
    with STATS_LOCK:
        value=read_stats(config_root,key)
        if value['day']!=_day(zone):
            value.update(day=_day(zone),requests=0,successful=0,failed=0,audio_seconds=0,quota={})
        value['timezone']=zone
        value['requests']+=1;value['audio_seconds']=round(value['audio_seconds']+seconds,2)
        value['successful' if successful else 'failed']+=1
        value['last_status']=status
        value['updated_at']=datetime.now(timezone.utc).isoformat()
        value['quota']={}
        for name in ('limit_requests','remaining_requests','reset_requests','retry_after','limit_audio_seconds','remaining_audio_seconds','reset_audio_seconds'):
            header='retry-after' if name=='retry_after' else 'x-ratelimit-'+name.replace('_','-')
            v=headers.get(header)
            if isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9 .:+-]{1,60}',v):value['quota'][name]=v
        value['key_id']=hashlib.sha256(key.encode()).hexdigest()
        write_owned(Path(config_root)/'.storage'/STATS,json.dumps(value))


def read_settings(config_root):
    path = Path(config_root) / '.storage' / SETTINGS
    if not path.exists():
        return {'enabled': False, 'key': ''}
    if path.is_symlink():
        raise ValueError('Speech settings cannot use symbolic links.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Speech settings need attention.')
    return {'enabled': value.get('enabled') is True, 'key': value.get('key', '')}


def public_settings(value):
    return {'enabled': value.get('enabled') is True, 'key_saved': bool(value.get('key'))}


def save_settings(config_root, body):
    if not isinstance(body, dict) or type(body.get('enabled')) is not bool:
        raise ValueError('Choose whether to enable Groq speech.')
    current = read_settings(config_root)
    supplied = body.get('key', '')
    if not isinstance(supplied, str):
        raise ValueError('Enter a valid Groq API key.')
    key = '' if body.get('clear_key') is True else supplied.strip() or current['key']
    if key and not re.fullmatch(r'gsk_[A-Za-z0-9_-]{20,200}', key):
        raise ValueError('Enter a valid Groq API key.')
    if body['enabled'] and not key:
        raise ValueError('Enter your Groq API key before enabling speech.')
    value = {'enabled': body['enabled'], 'key': key}
    write_owned(Path(config_root) / '.storage' / SETTINGS, json.dumps(value))
    return public_settings(value)
