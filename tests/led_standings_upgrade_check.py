"""An existing hub gets standings options without deleting/downloading its cards."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'pixora_led_displays'
SOURCE=Path('D:/planner/.build-tmp/led-public-card-source/cards')
sys.path[:0]=[str(APP),str(APP/'custom_components/pixora_local')]
from studio import Studio

class NoNetwork:
    def get(self,*args,**kwargs):raise AssertionError('An app upgrade attempted to redownload existing cards')

catalog=json.loads((APP/'card_catalog.json').read_text(encoding='utf-8'))
cards=[card for card in catalog['cards'] if 'standings' in card['id']]
with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);downloaded=root/'downloaded-cards'
    for name in {name for card in cards for name in card['files']}:
        target=downloaded/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(SOURCE/name,target)
    before={str(path.relative_to(downloaded)):path.read_bytes() for path in downloaded.rglob('*') if path.is_file()}
    saved={'decks':{'old':{'name':'Existing standings','items':[{'id':'nfl','card':'nfl_standings','options':{'group':'afc'},'duration':10,'enabled':True}]}},'devices':{},'groups':{},'graphics':{},'settings':{}}
    (root/'studio.json').write_text(json.dumps(saved),encoding='utf-8')
    studio=Studio({'session':NoNetwork()},root,lambda ident:None,lambda:[])
    public={card['id']:card for card in studio.public()['cards']}
    for card in cards:
        updated=public[card['id']]
        assert updated['installed'] and updated['standingsBrowser'],card['id']
        key='division' if updated['standingsBrowser']=='fantasy' else 'group'
        assert any(option['key']==key for option in updated['options']),card['id']
    assert studio.data==saved,'Upgrade changed existing decks or playback configuration'
    assert before=={str(path.relative_to(downloaded)):path.read_bytes() for path in downloaded.rglob('*') if path.is_file()},'Existing card files were replaced'
    print(f'Standings upgrade passed: all {len(cards)} previously downloaded cards gain current selection controls; no network, redownload, deletion or saved-deck changes.')
