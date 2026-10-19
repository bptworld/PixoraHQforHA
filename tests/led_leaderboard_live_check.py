"""Leaderboard cards detect live events even when season standings exist."""
import importlib.util,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'cards'))
import event_sport_utils as events
spec=importlib.util.spec_from_file_location('nascar',root/'cards/addons/nascar.py');nascar=importlib.util.module_from_spec(spec);spec.loader.exec_module(nascar)
for width in (64,128):
 for phase in ('pre','in','post'):
  event={'id':'race','status':{'type':{'state':phase}},'competitions':[]}
  events._fetch_events=lambda *args:[event]
  events._pick_event=lambda data:data[0]
  events._fetch_standings_rows=lambda *args:['season']
  events._leader_rows=lambda *args:['live']
  drawn=[]
  events._draw_leader_row=lambda image,draw,row,*args,**kwargs:drawn.append(row)
  events._fmt_event_time=lambda event:'Race'
  meta={};body=events.render_event_sport_card('racing','f1','F1',(0,200,0),'NO RACE',options={'_target':f'matrixportal-s3-{width}x32','_sports_meta':meta},leaderboard_only=True)
  assert body and meta['live'] is (phase=='in')
  assert drawn==(['live'] if phase=='in' else ['season']),drawn
  nascar._fetch_rows=lambda:[]
  meta={};assert nascar.render({'_sports_meta':meta})
  assert meta['live'] is (phase=='in')
print('Leaderboard live-state checks passed: live event rows beat season standings; F1 and NASCAR pre/live/final at both widths.')
