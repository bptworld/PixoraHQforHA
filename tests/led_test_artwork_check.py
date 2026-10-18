"""Graphic tests must include provider team assets and select the wall renderer."""
import base64,importlib.util,io,json,os,sys
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageSequence
ROOT=Path(__file__).resolve().parents[1]
source=Path('D:/planner/.build-tmp/led-public-card-source/cards')
os.chdir(source)
sys.path[:0]=[str(source),str(source/'addons'),str(ROOT/'pixora_led_displays')]
from special_graphics import render_test,test_team
import _sports_wall
catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text(encoding='utf-8'))
card=next(c for c in catalog['cards'] if c['id']=='nhl')
spec=importlib.util.spec_from_file_location('test_nhl',source/'addons/nhl.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
logo_url='https://a.espncdn.com/i/teamlogos/nhl/500/bos.png'
fixture={'team':{'id':'1','abbreviation':'BOS','displayName':'Boston Bruins','color':'FFB81C','alternateColor':'000000','logos':[{'href':logo_url}]}}
logo=Image.new('RGBA',(22,22),(255,0,255,255))
seen=[]
def asset(url):seen.append(url);return logo.copy()
with patch('card_utils.fetch_json_request',return_value=fixture) as provider,patch.object(_sports_wall,'_fetch_logo',side_effect=asset):
    team,warning=test_team(module,card,{'favoriteTeam':'BOS'},256)
    assert not warning and team['logo']==logo_url and team['color']=='FFB81C'
    assert provider.call_args.args[0].endswith('/hockey/nhl/teams/BOS')
    result=render_test(module,card,'goalAnimationTarget',{'favoriteTeam':'BOS','goalAnimationTarget':'group_wall'},256)
    assert logo_url in seen,'Wall renderer was not given the team logo'
    with Image.open(io.BytesIO(base64.b64decode(result['body']))) as image:
        assert image.size==(256,32) and image.n_frames>1
        assert any((255,0,255) in frame.convert('RGB').getdata() for frame in ImageSequence.Iterator(image)),'Logo pixels were lost from rendered wall artwork'
    assert 'warning' not in result
with patch('card_utils.fetch_json_request',side_effect=OSError('offline')):
    _,warning=test_team(module,card,{'favoriteTeam':'BOS'},64)
    assert 'fallback' in warning
with patch('card_utils.fetch_json_request',return_value={'team':{'abbreviation':'BOS'}}):
    _,warning=test_team(module,card,{'favoriteTeam':'BOS'},64)
    assert 'logo' in warning
print('Test artwork passed: provider metadata, correct team URL/colors/logo, wall-specific scenes, preserved logo pixels and explicit provider-failure feedback.')
