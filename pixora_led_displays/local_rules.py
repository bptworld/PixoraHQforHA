"""Local, minute-resolution Studio schedules."""
import asyncio
from datetime import date, datetime
import logging
import re
import time
from zoneinfo import ZoneInfo


def validate_schedule(value):
    if not isinstance(value, dict):
        raise ValueError('Choose a schedule.')
    dates = {}
    for key, label in (('startDate', 'start'), ('endDate', 'end')):
        day = value.get(key)
        if day is None or day == '':
            continue
        try:
            if not isinstance(day, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day):
                raise ValueError()
            dates[key] = date.fromisoformat(day).isoformat()
        except ValueError:
            raise ValueError(f'Choose a valid {label} date.') from None
    if dates.get('startDate') and dates.get('endDate') and dates['startDate'] > dates['endDate']:
        raise ValueError('End date must be on or after the start date.')
    kind = value.get('kind')
    if kind == 'hourly':
        minute = value.get('minute')
        if type(minute) is not int or not 0 <= minute <= 59:
            raise ValueError('Choose a minute from 0 to 59.')
        return {'kind': kind, 'minute': minute, **dates}
    if kind == 'interval':
        minutes = value.get('minutes')
        if type(minutes) is not int or not 1 <= minutes <= 1440:
            raise ValueError('Choose an interval from 1 to 1440 minutes.')
        return {'kind': kind, 'minutes': minutes, **dates}
    if kind == 'days':
        clock = value.get('time')
        days = value.get('days')
        if not isinstance(clock, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', clock):
            raise ValueError('Choose a time of day.')
        if not isinstance(days, list) or not 1 <= len(days) <= 7 or any(type(day) is not int or not 0 <= day <= 6 for day in days):
            raise ValueError('Choose at least one day of the week.')
        return {'kind': kind, 'time': clock, 'days': sorted(set(days)), **dates}
    raise ValueError('Choose a schedule type.')


def due(schedule, epoch_minute, timezone):
    kind = schedule['kind']
    if kind == 'interval' and epoch_minute % schedule['minutes'] != 0:
        return False
    start, end = schedule.get('startDate'), schedule.get('endDate')
    if kind == 'interval' and not (start or end):
        return True
    local = datetime.fromtimestamp(epoch_minute * 60, ZoneInfo(timezone))
    if start or end:
        day = local.date().isoformat()
        if (start and day < start) or (end and day > end):
            return False
    if kind == 'interval':
        return True
    if local.fold:
        return False  # A repeated local time when clocks fall back runs once.
    if kind == 'hourly':
        return local.minute == schedule['minute']
    return local.weekday() in schedule['days'] and local.strftime('%H:%M') == schedule['time']


async def run(studio):
    last_minute = int(time.time() // 60)
    while not (studio.root / '.cleanup-started').exists():
        now = time.time()
        minute = int(now // 60)
        if minute <= last_minute:
            await asyncio.sleep(max(.1, min(60, (minute + 1) * 60 - now)))
            continue
        last_minute = minute
        if now - minute * 60 > 15:
            continue
        timezone = studio.data.get('settings', {}).get('timezone', 'UTC')
        for ident, rule in list(studio.data.get('rules', {}).items()):
            if time.time() >= (minute + 1) * 60:
                break
            try:
                if rule['enabled'] and due(rule['schedule'], minute, timezone):
                    await studio.run_rule(ident, rule, minute)
            except ValueError as exc:
                studio.rule_status[ident] = str(exc)
            except Exception:
                logging.exception('Scheduled LED card could not run.')
                studio.rule_status[ident] = 'Could not play the scheduled card.'
