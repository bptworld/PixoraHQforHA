"""Validate the public HA app boundary before publishing."""
from pathlib import Path
import ast,json
import yaml
ROOT=Path(__file__).resolve().parents[1]
APPS={'haflow','pixora_home_control','pixora_locator','pixora_led_displays','pixora_voice','pixora_thermostat_controller','pixora_insight'}
found={path.parent.name for path in ROOT.glob('*/config.yaml')}
assert found==APPS,found
for name in sorted(APPS):
    folder=ROOT/name
    config=yaml.safe_load((folder/'config.yaml').read_text(encoding='utf-8'))
    assert config['slug']==name and isinstance(config['version'],str)
    assert config['url']=='https://github.com/bptworld/PixoraHQforHA/tree/main/'+name
    assert config['arch'] and (folder/'Dockerfile').is_file() and (folder/'README.md').is_file()
    for path in folder.rglob('*.py'):
        if '__pycache__' not in path.parts:ast.parse(path.read_text(encoding='utf-8'))
    for path in folder.rglob('*.json'):
        if not any(part in ('node_modules','dist') for part in path.parts):json.loads(path.read_text(encoding='utf-8'))
    for path in folder.rglob('*'):
        if not path.is_file() or 'node_modules' in path.parts:continue
        assert path.name not in {'.env','options.json','displays.json','credentials.json'},path
        # Existing tested first-install image is an app runtime asset, not source.
        if path!=ROOT/'pixora_led_displays/first-install.bin':
            assert path.suffix not in {'.bin','.pem','.key','.cpp','.ino','.h','.hpp'},path
    print(name+': '+config['version']+' checked')
assert yaml.safe_load((ROOT/'repository.yaml').read_text())['url']=='https://github.com/bptworld/PixoraHQforHA'
print(f'All {len(APPS)} public HA app packages passed.')
