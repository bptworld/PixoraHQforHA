"""All standings cards expose grouping; provider IDs select only their own rows."""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];SOURCE=Path('D:/planner/.build-tmp/led-public-card-source/cards')
sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(SOURCE),str(SOURCE/'addons')]
from standings import configure,public_card,endpoint,install,fantasy_groups,FANTASY
catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text(encoding='utf-8'))
cards={c['id']:c for c in catalog['cards']};configure(cards)
standings=[c for c in cards.values() if 'standings' in c['id']]
assert standings and all(c.get('standingsBrowser') for c in standings),[c['id'] for c in standings if not c.get('standingsBrowser')]
def entry(name):return {'team':{'id':name,'abbreviation':name},'stats':[{'type':'wins','displayValue':'3'},{'type':'losses','displayValue':'1'}]}
root={'children':[{'id':'8','name':'First conference','standings':{'entries':[entry('ALL')]}},{'id':'7','name':'Other conference','standings':{'entries':[entry('WRNG')]}}]}
leaf={'id':'42','name':'Selected division','standings':{'entries':[entry('ONLY')]},'children':[]}
def fetch(url,seconds=600):return leaf if '?group=42' in url else root
public=[]
for card in standings:
    if not public_card(card):continue
    public.append(card['id']);opts={o['key']:o.get('default','') for o in card['options']};opts['group']='espn:42'
    assert endpoint(card,opts).startswith('https://site.web.api.espn.com/')
    spec=importlib.util.spec_from_file_location('audit_'+card['module'],SOURCE/'addons'/(card['module']+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with patch('card_utils.fetch_json_request',side_effect=fetch):
        install(module,card['module'],opts)
        shared=module if card['module']=='sports_standings' else sys.modules['sports_standings']
        league=card['id'].removesuffix('_standings')
        if league=='sports':league='mlb'
        title,color,rows=shared._standings({**opts,'league':league})
        assert [row[1] for row in rows]==['ONLY'],(card['id'],rows)
        # A selected conference retains the provider's conference ordering.
        install(module,card['module'],{**opts,'group':'espn:8'})
        _,_,rows=shared._standings({**opts,'league':league,'group':'espn:8'})
        assert [row[1] for row in rows]==['ALL']
        try:shared._pick_child(root['children'],'espn:999')
        except ValueError:pass
        else:raise AssertionError('Missing division selected a different conference')

import _fantasy_sleeper as sleeper
sleeper_rows=[{'settings':{'division':1}},{'settings':{'division':2}}]
module=SimpleNamespace(rosters=lambda lid:sleeper_rows)
install(module,'fantasy_standings',{'division':'2'})
assert module.rosters('league')==sleeper_rows[1:]
with patch.object(sleeper,'league',return_value={'metadata':{'division_1':'East','division_2':'West'}}),patch.object(sleeper,'rosters',return_value=sleeper_rows):
    assert fantasy_groups(module,'fantasy_standings',{'leagueId':'123'})['groups']==[{'value':'1','label':'East'},{'value':'2','label':'West'}]
espn_data={'teams':[{'divisionId':0,'id':1},{'divisionId':1,'id':2}],'settings':{'scheduleSettings':{'divisions':[{'id':0,'name':'North'},{'id':1,'name':'South'}]}}}
module=SimpleNamespace(fetch_league=lambda opts:espn_data,league_id=lambda opts:'123')
install(module,'espn_fantasy_standings',{'division':'1'})
assert module.fetch_league({})['teams']==espn_data['teams'][1:]
assert len(fantasy_groups(module,'espn_fantasy_standings',{})['groups'])==2
import _fantasy_yahoo as yahoo
module=SimpleNamespace(standings=yahoo.standings)
install(module,'yahoo_fantasy_standings',{'division':'2'})
data={'teams':[{'team':[{'team_key':'l.t.1','name':'One'},{'team_standings':{'rank':1,'division_id':1}}]},{'team':[{'team_key':'l.t.2','name':'Two'},{'team_standings':{'rank':2,'division_id':2}}]}]}
settings={'divisions':[{'division':{'division_id':1,'name':'North'}},{'division':{'division_id':2,'name':'South'}}]}
with patch.object(yahoo,'get_json',side_effect=lambda path,*args,**kwargs:settings if path.endswith('/settings') else data):
    opts={'leagueKey':'l','accessToken':'secret'}
    with patch.object(yahoo,'league_key',return_value='l'),patch.object(yahoo,'access_token',return_value='secret'):
        assert [row['name'] for row in module.standings(opts)]==['Two']
        assert len(fantasy_groups(module,'yahoo_fantasy_standings',opts)['groups'])==2
print(f'Standings divisions passed: all {len(standings)} cards audited, {len(public)} public card renderers, exact provider IDs, no wrong-division fallback and all three fantasy providers.')

# Division discovery reuses saved private-league credentials without returning them.
import asyncio,tempfile
sys.path.insert(0,str(ROOT/'pixora_led_displays/custom_components/pixora_local'))
from studio import Studio
async def private_check():
    with tempfile.TemporaryDirectory() as folder:
        studio=Studio({'session':object()},Path(folder),lambda ident:None,lambda:[])
        studio.data['decks']['private']={'name':'Private','items':[{'id':'saved','card':'espn_fantasy_standings','options':{'leagueId':'123','espnS2':'keep-secret','swid':'keep-private'},'duration':10}]}
        captured=[]
        async def worker(request):captured.append(request);return {'groups':[{'value':'1','label':'East'}]}
        studio.run_worker=worker
        result=await studio.standings_groups({'card':'espn_fantasy_standings','deck':'private','item':'saved','options':{'leagueId':'123','espnS2':'','swid':''}})
        assert captured[0]['options']['espnS2']=='keep-secret' and captured[0]['options']['swid']=='keep-private'
        assert 'keep-secret' not in json.dumps(result) and 'keep-private' not in json.dumps(result)
asyncio.run(private_check())
print('Private standings discovery passed: saved credentials retained on hub and excluded from group responses.')
