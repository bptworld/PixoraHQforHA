"""Explicit group targets must not select the first overlapping group."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pixora_led_displays/custom_components/pixora_local'))
from special_graphics import event_group
from studio import Studio
card={'id':'nhl','options':[{'key':'goalAnimationTarget','label':'Goal'}]}
groups={'a':[('left',64),('center',128)],'b':[('left',64),('right',64)]}
assert event_group({'type':'goal'},{'goalAnimationTarget':'group:b'},card,groups)==groups['b']
assert event_group({'type':'goal'},{'goalAnimationTarget':'group:a'},card,groups)==groups['a']
assert event_group({'type':'field_goal'},{'scoreAnimationTarget':'group:b','winAnimationTarget':'group:a'}, {'id':'nfl','options':[]},groups)==groups['b']
for target in ('group_wall','group:deleted'):
    try:event_group({'type':'goal'},{'goalAnimationTarget':target},card,groups)
    except ValueError:pass
    else:raise AssertionError('Ambiguous/deleted group must not fall back')
studio=Studio.__new__(Studio)
studio.data={'groups':{key:{'members':[m for m,_ in members]} for key,members in groups.items()}}
assert studio.graphic_group('left','group:b') is studio.data['groups']['b']
for target in ('group_wall','group:deleted'):
    try:studio.graphic_group('left',target)
    except ValueError:pass
    else:raise AssertionError('Test must not choose an arbitrary group')
assert event_group({'type':'goal'},{'goalAnimationTarget':'group_wall'},card,{'a':groups['a']})==groups['a']
print('Group targets passed: explicit overlapping groups, test routing, legacy single group, missing/ambiguous rejection.')
