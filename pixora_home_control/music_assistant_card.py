"""Bounded, read-only Music Assistant access through HA's authenticated socket."""
import re

MEDIA_TYPES = {'track', 'album', 'artist', 'playlist', 'radio', 'podcast', 'audiobook'}


async def read_music(local, payload):
    if not isinstance(payload, dict):
        raise ValueError('Invalid music request.')
    operation = payload.get('operation')
    if operation == 'players':
        registry = await local.query('config/entity_registry/list')
        return {'players': sorted(item['entity_id'] for item in registry
                if item.get('platform') == 'music_assistant'
                and str(item.get('entity_id', '')).startswith('media_player.')
                and not item.get('disabled_by'))}
    entity = payload.get('entityId', '')
    if not isinstance(entity, str) or not re.fullmatch(r'media_player\.[a-z0-9_]+', entity):
        raise ValueError('Choose a Music Assistant player.')
    entry = await local.query('config/entity_registry/get', entity_id=entity)
    if not isinstance(entry, dict) or entry.get('platform') != 'music_assistant' or not entry.get('config_entry_id'):
        raise ValueError('Choose a Music Assistant player.')
    if operation == 'artwork':
        return await local.music_artwork(entity)
    if operation == 'queue':
        service, data = 'get_queue', {'entity_id': entity}
    elif operation in {'search', 'favorites'}:
        kind = payload.get('mediaType', 'track')
        if kind not in MEDIA_TYPES:
            raise ValueError('Choose a supported music type.')
        data = {'config_entry_id': entry['config_entry_id'], 'media_type': kind, 'limit': 20}
        if operation == 'search':
            query = payload.get('query')
            if not isinstance(query, str) or not 1 <= len(query.strip()) <= 160:
                raise ValueError('Enter a music search.')
            service = 'search'
            data['name'] = query.strip()
        else:
            service = 'get_library'
            data.update(favorite=True, order_by='name')
    else:
        raise ValueError('Unsupported music request.')
    result = await local.query('call_service', domain='music_assistant', service=service,
                               service_data=data, return_response=True)
    return result.get('response') or {}
