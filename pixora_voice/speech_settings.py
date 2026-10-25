"""Hub-owned optional speech credentials. Never return the key to the browser."""
import json
import re
from pathlib import Path
from planner_phrases import write_owned

SETTINGS = 'pixora_voice_speech.json'


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
