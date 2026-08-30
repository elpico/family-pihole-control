import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .categories import CATEGORIES
from .scheduler import Schedule, parse_time


class ScheduleValidationError(ValueError):
    pass


@dataclass
class SchedulerState:
    paused: bool = False
    last_enforced: dict = field(default_factory=dict)


def new_schedule_id():
    return uuid.uuid4().hex[:8]


def _as_day(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _validate_fields(name, days, start, end, categories):
    if not isinstance(name, str):
        raise ScheduleValidationError("name must be a string.")
    day_values = [_as_day(d) for d in days] if isinstance(days, list) else []
    if (
        not isinstance(days, list)
        or not days
        or any(
            day is None or not 0 <= day <= 6
            for day in day_values
        )
        or len(set(day_values)) != len(day_values)
    ):
        raise ScheduleValidationError(
            "days must be a non-empty list of 0-6 without repeats."
        )
    try:
        parse_time(start)
        parse_time(end)
    except ValueError as exc:
        raise ScheduleValidationError(str(exc)) from exc
    if (
        not isinstance(categories, list)
        or not categories
        or len(set(categories)) != len(categories)
        or any(category not in CATEGORIES for category in categories)
    ):
        raise ScheduleValidationError(
            "categories must be a non-empty list of known categories."
        )


def _normalise(name, days, start, end, categories):
    _validate_fields(name, days, start, end, categories)
    return {
        "name": name.strip(),
        "days": sorted(set(_as_day(d) for d in days)),
        "start": start,
        "end": end,
        "categories": [c for c in CATEGORIES if c in categories],
    }


def schedule_from_dict(data):
    if not isinstance(data, dict):
        raise ScheduleValidationError("schedule must be an object.")
    name = data.get("name") or ""
    if not isinstance(name, str):
        raise ScheduleValidationError("name must be a string.")
    schedule_id = str(data.get("id") or "")
    if not schedule_id:
        raise ScheduleValidationError("schedule id is required.")
    fields = _normalise(
        name,
        data.get("days"),
        str(data.get("start") or ""),
        str(data.get("end") or ""),
        data.get("categories"),
    )
    return Schedule(id=schedule_id, **fields)


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


class ScheduleStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.schedules_path = self.directory / "schedules.json"
        self.state_path = self.directory / "scheduler-state.json"

    def load_schedules(self):
        try:
            raw = json.loads(self.schedules_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(raw, list):
            return []
        schedules = []
        for item in raw:
            try:
                schedules.append(schedule_from_dict(item))
            except ScheduleValidationError:
                continue
        return schedules

    def save_schedules(self, schedules):
        _atomic_write_json(
            self.schedules_path, [asdict(schedule) for schedule in schedules]
        )

    def load_state(self):
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return SchedulerState()
        if not isinstance(raw, dict):
            return SchedulerState()
        last_enforced = raw.get("last_enforced")
        if not isinstance(last_enforced, dict):
            last_enforced = {}
        return SchedulerState(
            paused=bool(raw.get("paused", False)),
            last_enforced={
                category: state
                for category, state in last_enforced.items()
                if category in CATEGORIES and state in ("BLOCKED", "ALLOWED")
            },
        )

    def save_state(self, state):
        _atomic_write_json(
            self.state_path,
            {"paused": state.paused, "last_enforced": state.last_enforced},
        )

    def add_schedule(self, name, days, start, end, categories):
        fields = _normalise(name, days, start, end, categories)
        schedules = self.load_schedules()
        schedule = Schedule(new_schedule_id(), **fields)
        schedules.append(schedule)
        self.save_schedules(schedules)
        return schedule

    def update_schedule(self, schedule_id, name, days, start, end, categories):
        fields = _normalise(name, days, start, end, categories)
        schedules = self.load_schedules()
        for index, schedule in enumerate(schedules):
            if schedule.id == schedule_id:
                updated = Schedule(schedule_id, **fields)
                schedules[index] = updated
                self.save_schedules(schedules)
                return updated
        return None

    def delete_schedule(self, schedule_id):
        schedules = self.load_schedules()
        remaining = [s for s in schedules if s.id != schedule_id]
        if len(remaining) == len(schedules):
            return False
        self.save_schedules(remaining)
        return True
