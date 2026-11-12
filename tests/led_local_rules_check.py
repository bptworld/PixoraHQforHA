"""Regression checks for scheduled LED cards and wall delivery."""
import asyncio
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

APP = Path(__file__).resolve().parents[1] / 'pixora_led_displays'
sys.path[:0] = [str(APP), str(APP / 'custom_components/pixora_local')]
from local_rules import due, validate_schedule
from pipeline import quiet_card
from studio import Studio


def minute(value, fold=0):
    stamp = datetime.fromisoformat(value).replace(tzinfo=ZoneInfo('America/New_York'), fold=fold)
    return int(stamp.timestamp() // 60)


def schedules():
    timezone = 'America/New_York'
    hourly = validate_schedule({'kind': 'hourly', 'minute': 0})
    assert due(hourly, minute('2026-11-12T19:00'), timezone)
    assert not due(hourly, minute('2026-11-12T19:01'), timezone)
    assert due(hourly, minute('2026-11-01T01:00'), timezone)
    assert not due(hourly, minute('2026-11-01T01:00', fold=1), timezone)
    days = validate_schedule({'kind': 'days', 'time': '19:00', 'days': [3, 3]})
    assert due(days, minute('2026-11-12T19:00'), timezone)
    assert not due(days, minute('2026-11-13T19:00'), timezone)
    interval = validate_schedule({'kind': 'interval', 'minutes': 15})
    assert due(interval, 45, timezone) and not due(interval, 46, timezone)
    for invalid in ({'kind': 'hourly', 'minute': 60}, {'kind': 'interval', 'minutes': True},
                    {'kind': 'days', 'time': '25:00', 'days': [0]}, {'kind': 'days', 'time': '09:00', 'days': []}):
        try:
            validate_schedule(invalid)
        except ValueError:
            continue
        raise AssertionError(f'Accepted invalid schedule {invalid}')


async def playback():
    with tempfile.TemporaryDirectory() as folder:
        studio = Studio.__new__(Studio)
        studio.root = Path(folder)
        studio.lock = asyncio.Lock()
        studio.rule_status = {}
        studio.store = SimpleNamespace(cards={'turkey_chase': {'wallWidths': [64, 128, 64]}})
        studio.data = {'rules': {}, 'decks': {}, 'devices': {}, 'groups': {'wall': {'members': ['left','center','right']}}}
        studio.displays = lambda: [{'id': i, 'width': w} for i, w in zip(('left','center','right'), (64,128,64))]
        studio.quiet = lambda cfg: bool(cfg.get('quiet'))
        submitted = []
        async def submit(entries):
            submitted.append(entries)
        studio.pipeline = SimpleNamespace(submit=submit)
        async def graphic(payload, scheduled):
            assert payload['options']['wallTarget'] == 'group:wall'
            slices = [('left',64,'a'),('center',128,'b'),('right',64,'c')]
            await studio.queue_rule(scheduled, {'duration': 13, 'once': True}, slices, ['left','center','right'])
        studio.test_graphic = graphic
        rule = studio.validate_rule({'name':'Turkey Chase','card':'turkey_chase','target':'wall',
                                     'schedule':{'kind':'hourly','minute':0}})
        studio.data['rules']['r'] = rule
        assert studio.used() == {'turkey_chase'}
        await studio.run_rule('r',rule,int(time.time() // 60))
        assert len(submitted) == 1
        assert [ident for ident,_ in submitted[0]] == ['left','center','right']
        assert len({entry['event_id'] for _,entry in submitted[0]}) == 1
        assert len({entry['start_at'] for _,entry in submitted[0]}) == 1
        studio.data['devices']['right'] = {'quiet':True}
        assert quiet_card(studio, 'left', submitted[0][0][1])
        await studio.run_rule('r',rule)
        assert len(submitted) == 1 and 'quiet hours' in studio.rule_status['r']
        studio.data['devices'].clear()
        await studio.run_rule('r',rule,int(time.time() // 60)-1)
        assert len(submitted) == 1 and 'past the scheduled minute' in studio.rule_status['r']
        studio.data['rules']['r'] = {**rule, 'revision':'edited'}
        await studio.run_rule('r',rule)
        assert len(submitted) == 1


if __name__ == '__main__':
    schedules()
    asyncio.run(playback())
    print('Local rules passed: time zones, repeated hour, selected days, interval, wall queue, quiet hours and stale runs.')
