import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .categories import CATEGORIES

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
HORIZON_DAYS = 8
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass
class Schedule:
    id: str
    name: str
    days: list
    start: str
    end: str
    categories: list


def parse_time(value):
    match = _TIME_RE.match(value) if isinstance(value, str) else None
    if not match:
        raise ValueError(f"invalid time: {value!r}")
    return time(int(match.group(1)), int(match.group(2)))


def end_crosses_midnight(schedule):
    return parse_time(schedule.end) <= parse_time(schedule.start)


def window_end_for(schedule, day):
    end = parse_time(schedule.end)
    offset = timedelta(days=1) if end_crosses_midnight(schedule) else timedelta()
    return datetime.combine(day, end) + offset


def is_active(schedule, moment):
    for offset in (0, -1):
        day = (moment + timedelta(days=offset)).date()
        if day.weekday() not in schedule.days:
            continue
        start = datetime.combine(day, parse_time(schedule.start))
        if start <= moment < window_end_for(schedule, day):
            return True
    return False


def active_schedules(schedules, moment):
    return [schedule for schedule in schedules if is_active(schedule, moment)]


def scheduled_states(schedules, moment):
    states = {}
    for category in CATEGORIES:
        states[category] = "BLOCKED" if any(
            category in schedule.categories
            for schedule in active_schedules(schedules, moment)
        ) else "ALLOWED"
    return states


def active_end(schedules, moment, category):
    ends = []
    for schedule in active_schedules(schedules, moment):
        if category not in schedule.categories:
            continue
        for offset in (0, -1):
            day = (moment + timedelta(days=offset)).date()
            start = datetime.combine(day, parse_time(schedule.start))
            if start <= moment < window_end_for(schedule, day):
                ends.append(window_end_for(schedule, day))
    return min(ends) if ends else None


def _boundaries(schedules, now):
    boundaries = set()
    for schedule in schedules:
        for offset in range(HORIZON_DAYS + 1):
            day = (now + timedelta(days=offset)).date()
            if day.weekday() not in schedule.days:
                continue
            boundaries.add(datetime.combine(day, parse_time(schedule.start)))
            boundaries.add(window_end_for(schedule, day))
    return sorted(boundary for boundary in boundaries if boundary > now)


def next_change(schedules, now):
    boundaries = _boundaries(schedules, now)
    if not boundaries:
        return None
    first = boundaries[0]
    before = scheduled_states(schedules, first - timedelta(seconds=1))
    after = scheduled_states(schedules, first)
    changes = {
        category: (before[category], after[category])
        for category in before
        if before[category] != after[category]
    }
    return first, changes


def describe_days(days):
    days = sorted(set(days))
    if days == list(range(7)):
        return "Every day"
    if days == [0, 1, 2, 3, 4]:
        return "Weekdays"
    if days == [5, 6]:
        return "Weekends"
    parts = []
    run = [days[0]]
    for day in days[1:]:
        if day == run[-1] + 1:
            run.append(day)
        else:
            parts.append(run)
            run = [day]
    parts.append(run)
    labels = [
        DAY_NAMES[run[0]]
        if len(run) == 1
        else f"{DAY_NAMES[run[0]]}–{DAY_NAMES[run[-1]]}"
        for run in parts
    ]
    return ", ".join(labels)


def describe_schedule(schedule):
    if schedule.name:
        return schedule.name
    return f"{describe_days(schedule.days)} {schedule.start}–{schedule.end}"


def describe_when(moment, now):
    if moment.date() == now.date():
        return "today"
    if moment.date() == (now + timedelta(days=1)).date():
        return "tomorrow"
    return DAY_NAMES[moment.weekday()]


def format_duration(delta):
    total = int(delta.total_seconds())
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes or not parts:
        parts.append(f"{minutes}m")
    return " ".join(parts)
