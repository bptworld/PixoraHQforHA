"""Offline transition checks for shared sports, commerce, weather and flight events."""
import importlib,io,os,sys,time
from pathlib import Path
from PIL import Image
source=Path('D:/planner/.build-tmp/led-public-card-source/cards')
os.chdir(source);sys.path[:0]=[str(source),str(source/'addons')]
out=io.BytesIO();Image.new('RGB',(64,32),'blue').save(out,'PNG');body=out.getvalue()
import card_utils
card_utils.warm_priority_graphic=lambda *args,**kwargs:None
card_utils.cached_priority_graphic=lambda *args,**kwargs:body
import _sports_breaking as sports
options={'favoriteTeam':'ALA','_device_id':'panel','_width':64}
team={'abbreviation':'ALA','displayName':'Alabama'}
for sport,delta in [('football',7),('basketball',3),('hockey',1),('lacrosse',1),('volleyball',1)]:
    state={};competitor={'score':'0','team':team};competition={'competitors':[competitor],'status':{'type':{'state':'in'}}}
    event={'id':'game','competitions':[competition]}
    sports.fetch_sport_scoreboard=lambda *args,**kwargs:{'events':[event]}
    sports.pick_sport_event=lambda *args:event
    check=lambda opts=options:sports.maybe_score_alert(opts,'card','url',{},state,sport=sport)
    assert check() is None
    competitor['score']=str(delta)
    assert check({**options,'_is_prefetch':True}) is None
    assert check()['_priority']
    assert check() is None,'Score animation repeated'
    competitor['winner']=True;competition['status']['type']['state']='post'
    assert check()['_priority'],'Final winner was not detected'
    assert check() is None,'Winner animation repeated'
for unit in ('quarter','period'):
    state={};competition={'status':{'period':1,'type':{'state':'in','description':'In progress'}}};event={'id':'period-game'}
    check=lambda:sports.game_moment_alert(options,'card',state,event,competition,team,unit=unit)
    assert check() is None
    competition['status']['period']=2
    assert check()['_priority'] and check() is None
    competition['status']['type']['description']='End of '+unit
    assert check()['_priority'] and check() is None

state={};competition={'status':{'period':1,'type':{'state':'pre','description':'Scheduled'}},'competitors':[]};event={'id':'soccer'}
def soccer_check():return sports.soccer_moment_alert(options,'soccer',state,event,competition,team)
assert soccer_check() is None
for period,phase,description in [(1,'in','In progress'),(1,'in','Halftime'),(2,'in','In progress'),(2,'post','Final')]:
    competition['status']={'period':period,'type':{'state':phase,'description':description}}
    assert soccer_check()['_priority'] and soccer_check() is None

import mlb
competitor={'team':team,'score':'0'}
competition={'status':{'period':1,'type':{'state':'in','description':'Top 1st'}},'competitors':[competitor]}
event={'id':'baseball','competitions':[competition]}
def inning_check():return mlb._maybe_inning_animation(options,event,competition,[competitor],'ALA')
assert inning_check() is None
competition['status']['type']['description']='End of inning'
assert inning_check()['_priority'] and inning_check() is None
competition['status']={'period':2,'type':{'state':'in','description':'Top 2nd'}}
assert inning_check()['_priority'] and inning_check() is None

import ufc
ufc._warm_moment_test_graphics=lambda *args:None
ufc._result_kind=lambda event,competition:competition.get('fixture_result','')
competition={'id':'fight','status':{'period':1,'displayClock':'5:00','type':{'state':'pre'}},'competitors':[]}
event={'id':'fight'}
def fight_check():return ufc._maybe_moment_animation(options,event,competition)
assert fight_check() is None
competition['status']['type']['state']='in'
assert fight_check()['_priority'] and fight_check() is None
competition['status']['period']=2
assert fight_check()['_priority'] and fight_check() is None
competition['status']['displayClock']='0:00'
assert fight_check()['_priority'] and fight_check() is None
for kind in ('knockout','submission','decision','win'):
    ufc._MOMENT_STATE.clear();competition['competitors']=[];competition['fixture_result']=''
    assert fight_check() is None
    competition['competitors']=[{'winner':True,'athlete':{'displayName':'Test Winner','lastName':'Winner'}}]
    competition['fixture_result']=kind
    assert fight_check()['_priority'] and fight_check() is None

import etsy_shop as etsy
for width in (64,128):
    actual=etsy._new_order_animation({'newest_total':12.5,'newest_currency':'USD'},{'_target':'matrixportal-s3-'+str(width)+'x32'})
    with Image.open(io.BytesIO(actual)) as image:assert image.size==(width,32) and image.n_frames>1
etsy._headers=lambda opts:{'key':'fixture'}
data={'newest_id':'one'};etsy._etsy_data=lambda opts:data
etsy._render_card=lambda *args:body;etsy._new_order_animation=lambda *args:body
opts={'shopId':'fixture','accessToken':'fixture','_device_id':'panel'}
assert etsy.render(opts)==body
data['newest_id']='two';assert etsy.render(opts)['_no_replay'];assert etsy.render(opts)==body

import weather_alert as weather
for severity in ('Minor','Moderate','Severe','Extreme','Unknown'):
    alert={'id':severity,'properties':{'severity':severity,'event':'Weather Alert'}}
    assert weather._maybe_severity_animation({**options,'_is_prefetch':True},alert,'01826') is None
    assert weather._maybe_severity_animation(options,alert,'01826')['_priority']
    assert weather._maybe_severity_animation(options,alert,'01826') is None

import flight_watchlist as watch
item={'ident':'AA1','status':'Scheduled','gate':'A1','destination':'BOS'}
assert watch._alert_for({},[item],{})==(None,0)
for updates,near in [({'status':'Delayed'},{}),({'status':'Landed'},{}),({'gate':'B2'},{}),({}, {'AA1':{'near':True,'miles':10}})]:
    item.update(updates)
    assert watch._alert_for({},[item],near)[0] is not None
    assert watch._alert_for({},[item],near)==(None,0)

import flight_track as track
track._configured_slots=lambda opts:[{'_slot':1}];track._home_latlon=lambda *args:None
flight={'flight':'AA1','origin':'DFW','destination':'BOS','on_ground':False,'alt_ft':10000,'speed_kt':300}
track._load_live=lambda *args,**kwargs:(flight,None)
track._refresh_snapshot('fixture',{})
assert not track._SNAPSHOT_CACHE['fixture']['welcome']
flight.update(on_ground=True,alt_ft=0,speed_kt=0)
track._refresh_snapshot('fixture',{});assert track._SNAPSHOT_CACHE['fixture']['welcome']
track._refresh_snapshot('fixture',{});assert not track._SNAPSHOT_CACHE['fixture']['welcome']

import launch_countdown as launch
launch_fixture=launch._test_launch(0)
launch._pick_launch=lambda opts:launch_fixture
launch._draw_launch_page=lambda *args,**kwargs:Image.new('RGB',(64,32))
launch._seconds_until=lambda value:4
assert launch.render({**options,'_is_prefetch':True})
assert launch.render(options)['_priority_graphic']
assert not isinstance(launch.render(options),dict),'Shake animation repeated'
launch._seconds_until=lambda value:0
assert launch.render(options)['_priority_graphic']
assert not isinstance(launch.render(options),dict),'Liftoff animation repeated'
print('Special event transitions passed: scores, winners, quarter/period starts and ends, Etsy orders, five weather severities, flight delays/arrivals/gates/proximity/landings, launch shake/liftoff and duplicate suppression.')
