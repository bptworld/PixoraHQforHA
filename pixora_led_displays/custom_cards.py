"""Read custom card metadata without importing or executing uploaded Python."""
import ast
import hashlib
import json
import re

MAX_SOURCE = 256 * 1024


def describe(body):
    if not body or len(body) > MAX_SOURCE:
        raise ValueError('Choose a Python card file smaller than 256 KB.')
    try:
        source = body.decode('utf-8-sig')
        tree = ast.parse(source)
    except (UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
        raise ValueError('The card must be valid UTF-8 Python.') from exc
    values = {}
    fields = {'CARD_ID', 'CARD_NAME', 'CARD_DETAIL', 'CARD_VERSION', 'CARD_AUTHOR', 'CARD_OPTIONS'}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in fields:
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError, RecursionError) as exc:
                        raise ValueError(target.id + ' must be a literal value, not a function call.') from exc
    ident = values.get('CARD_ID')
    if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,47}', ident):
        raise ValueError('CARD_ID must use lowercase letters, numbers and underscores, starting with a letter (up to 48 characters).')
    for key, limit in [('CARD_NAME', 80), ('CARD_DETAIL', 300), ('CARD_VERSION', 32), ('CARD_AUTHOR', 80)]:
        value = values.get(key, '' if key != 'CARD_NAME' else None)
        if not isinstance(value, str) or len(value) > limit or (key == 'CARD_NAME' and not value.strip()):
            raise ValueError(key + ' must be a short text value.')
    if not any(isinstance(node, ast.FunctionDef) and node.name == 'render' for node in tree.body):
        raise ValueError('The card must define render(options=None).')
    options = values.get('CARD_OPTIONS', [])
    if not isinstance(options, list) or len(options) > 30:
        raise ValueError('CARD_OPTIONS must be a list of up to 30 options.')
    seen = set()
    for option in options:
        if not isinstance(option, dict):
            raise ValueError('Each card option must be an object.')
        key = option.get('key')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,47}', key) or key in seen:
            raise ValueError('Card option keys must be unique and cannot start with an underscore.')
        seen.add(key)
        if not isinstance(option.get('label'), str) or not 1 <= len(option['label']) <= 80:
            raise ValueError('Each option needs a short label.')
        if option.get('type') not in ('text', 'password', 'number', 'checkbox', 'select', 'multiselect', 'date'):
            raise ValueError('Unsupported custom card option type.')
        if any(word in key.lower() for word in ('token', 'secret', 'password', 'apikey', 'api_key')):
            option['type'] = 'password'
        if option['type']=='password' and option.get('default') not in (None,''):
            raise ValueError('Password/API key defaults must be empty. Enter secrets in the app options instead.')
        if 'default' in option and not isinstance(option['default'], (str,int,float,bool)):
            raise ValueError('Option defaults must be text, numbers or booleans.')
        if option['type'] in ('select', 'multiselect'):
            choices = option.get('choices')
            if not isinstance(choices, list) or not 1 <= len(choices) <= 100:
                raise ValueError('Select options need 1 to 100 choices.')
            for choice in choices:
                if not isinstance(choice, str) and not (isinstance(choice, dict) and isinstance(choice.get('value'), (str, int, float)) and isinstance(choice.get('label'), str)):
                    raise ValueError('Invalid select choice.')
        if any(not isinstance(option[k], (int, float)) or isinstance(option[k], bool) for k in ('min', 'max', 'step', 'maxlength') if k in option):
            raise ValueError('Option limits must be numbers.')
    try:
        encoded = json.dumps(options, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('Options must contain ordinary JSON values.') from exc
    if len(encoded) > 16000:
        raise ValueError('Card options are too large.')
    custom_id = 'custom_' + ident
    return {'id': custom_id, 'module': custom_id, 'name': values['CARD_NAME'].strip(),
            'detail': values.get('CARD_DETAIL', ''), 'version': values.get('CARD_VERSION', ''),
            'author': values.get('CARD_AUTHOR', ''), 'category': 'My Apps', 'options': options,
            'custom': True, 'sourceHash': hashlib.sha256(body).hexdigest()}
