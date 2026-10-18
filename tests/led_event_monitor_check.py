"""Discover event producers that delegate scoring to public shared helpers."""
import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'pixora_led_displays'),str(ROOT/'pixora_led_displays/custom_components/pixora_local')]
from studio import Studio

async def check():
    source=Path('D:/planner/.build-tmp/led-public-card-source/cards')
    catalog=json.loads((ROOT/'pixora_led_displays/card_catalog.json').read_text(encoding='utf-8'))
    studio=Studio.__new__(Studio)
    cards={c['id']:c for c in catalog['cards']}
    expected=['etsy_shop','cfl','college_baseball','college_football','college_softball','fifa_world_cup','mens_college_basketball','mens_college_lacrosse','mlb','nba_g_league','nba','mens_college_hockey','nfl','nhl','nll_lacrosse','pll_lacrosse','soccer','ufc','ufl','wnba','womens_college_basketball','womens_college_lacrosse','womens_college_volleyball','flight_watchlist','flight_track','launch_countdown','weather_alert']
    ids=['clock',*expected]
    items=[{'id':ident,'card':ident,'enabled':True,'options':{'favoriteTeam':'ALA'}} for ident in ids]
    studio.data={'devices':{'panel':{'playing':True,'deck':'deck'}},'decks':{'deck':{'items':items}},'groups':{}}
    studio.store=SimpleNamespace(cards=cards,catalog=catalog,path=lambda name:source/name)
    studio.pipeline=SimpleNamespace(data={'states':{}})
    studio.monitor_errors={};studio.quiet=lambda cfg:False
    checked=[]
    async def info():return {'width':64}
    studio.selected=lambda ident:SimpleNamespace(info=info)
    studio.displays=lambda:[{'id':'panel','width':64}]
    async def render(item,width,**kwargs):
        assert kwargs['events'] and kwargs['request_only']
        return {'card_id':item['card']}
    async def render_request(request):
        checked.append(request['card_id'])
        assert request['state_key'] and request['event_state']=={}
        if request['card_id']==expected[-1]:studio.data['devices']['panel']['playing']=False
    studio.render=render;studio.render_request=render_request
    task=asyncio.create_task(studio.monitor('panel'))
    try:
        for _ in range(1000):
            if len(checked)==len(expected):break
            if task.done():await task
            await asyncio.sleep(.001)
        assert checked==expected,checked
        assert not studio.monitor_errors,studio.monitor_errors
    finally:
        task.cancel();await asyncio.gather(task,return_exceptions=True)
    # Launch's five-second shake window needs faster checks than provider sports cards.
    studio.data['devices']['panel']['playing']=True
    studio.data['decks']['deck']['items']=[row for row in items if row['card'] in ('college_football','launch_countdown')]
    clock=0;observed=[]
    async def scheduled_request(request):
        observed.append((request['card_id'],clock,request['state_key']))
    async def tick(seconds):
        nonlocal clock
        clock+=seconds
        studio.data['decks']['deck']['items'][0]['duration']=20
        if clock>=16:studio.data['devices']['panel']['playing']=False
    studio.render_request=scheduled_request
    with patch('studio.time',SimpleNamespace(monotonic=lambda:clock)),patch('studio.asyncio.sleep',tick):
        await studio.monitor('panel')
    football=[row for row in observed if row[0]=='college_football']
    assert [row[1] for row in football]==[0,15],football
    assert football[0][2]==football[1][2],'Duration-only edit reset scoring history'
    assert [row[1] for row in observed if row[0]=='launch_countdown']==list(range(16))
    print('Event monitor passed: all 27 special-event cards are checked; ordinary clock is skipped.')

asyncio.run(check())
