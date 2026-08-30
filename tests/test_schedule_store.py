import json

import pytest

from app.schedule_store import (
    ScheduleStore,
    ScheduleValidationError,
    SchedulerState,
    new_schedule_id,
    schedule_from_dict,
)
from app.scheduler import Schedule

VALID = {
    "name": "  Weekday evenings ",
    "days": ["3", 0, 1],
    "start": "17:00",
    "end": "19:00",
    "categories": ["gaming", "streaming"],
}


@pytest.fixture
def store(tmp_path):
    return ScheduleStore(tmp_path)


def test_new_schedule_id_is_short_hex():
    assert len(new_schedule_id()) == 8
    assert new_schedule_id() != new_schedule_id()


def test_add_schedule_normalises_and_persists(store):
    schedule = store.add_schedule(**VALID)

    assert schedule.name == "Weekday evenings"
    assert schedule.days == [0, 1, 3]
    assert schedule.categories == ["streaming", "gaming"]
    assert len(schedule.id) == 8

    loaded = store.load_schedules()
    assert loaded == [schedule]


def test_add_schedule_rejects_invalid_fields(store):
    invalid_bodies = [
        {**VALID, "days": []},
        {**VALID, "days": [7]},
        {**VALID, "days": [-1]},
        {**VALID, "days": [1, 1]},
        {**VALID, "days": "Monday"},
        {**VALID, "start": "24:00"},
        {**VALID, "end": "9:00"},
        {**VALID, "categories": []},
        {**VALID, "categories": ["streaming", "streaming"]},
        {**VALID, "categories": ["unknown"]},
        {**VALID, "name": 42},
    ]
    for body in invalid_bodies:
        with pytest.raises(ScheduleValidationError):
            store.add_schedule(**body)
    assert store.load_schedules() == []


def test_update_schedule_changes_fields_and_keeps_id(store):
    original = store.add_schedule(**VALID)
    updated = store.update_schedule(
        original.id, "New name", [5, 6], "21:00", "08:00", ["social-media"]
    )

    assert updated.id == original.id
    assert updated.name == "New name"
    assert updated.days == [5, 6]
    assert [schedule.id for schedule in store.load_schedules()] == [original.id]


def test_update_schedule_unknown_id_returns_none(store):
    assert store.update_schedule("nope", "x", [0], "09:00", "10:00",
                                 ["streaming"]) is None


def test_delete_schedule_removes_only_that_schedule(store):
    first = store.add_schedule(**VALID)
    second = store.add_schedule(name="Other", days=[2], start="10:00",
                                end="11:00", categories=["gaming"])

    assert store.delete_schedule(first.id) is True
    assert store.load_schedules() == [second]
    assert store.delete_schedule(first.id) is False
    assert store.delete_schedule("nope") is False


def test_load_schedules_without_files(store):
    assert store.load_schedules() == []
    assert store.load_state() == SchedulerState()


def test_load_schedules_recovers_from_corrupt_file(store):
    store.schedules_path.parent.mkdir(parents=True, exist_ok=True)
    store.schedules_path.write_text("not json", encoding="utf-8")
    assert store.load_schedules() == []


def test_load_schedules_skips_invalid_entries(store):
    good = {"id": "abcd1234", "name": "", "days": [0], "start": "09:00",
            "end": "10:00", "categories": ["streaming"]}
    bad = {**good, "id": "efgh5678", "days": []}
    store.schedules_path.parent.mkdir(parents=True, exist_ok=True)
    store.schedules_path.write_text(
        json.dumps([bad, good, "junk"]), encoding="utf-8"
    )
    assert store.load_schedules() == [schedule_from_dict(good)]


def test_load_state_recovers_from_corrupt_file(store):
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{", encoding="utf-8")
    assert store.load_state() == SchedulerState()


def test_load_state_filters_unknown_categories(store):
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text(
        json.dumps(
            {
                "paused": True,
                "last_enforced": {
                    "streaming": "BLOCKED",
                    "unknown": "BLOCKED",
                    "gaming": "MAYBE",
                },
            }
        ),
        encoding="utf-8",
    )
    state = store.load_state()
    assert state.paused is True
    assert state.last_enforced == {"streaming": "BLOCKED"}


def test_save_state_round_trips(store):
    state = SchedulerState(paused=True, last_enforced={"gaming": "ALLOWED"})
    store.save_state(state)
    assert store.load_state() == state


def test_save_schedules_replaces_file_atomically(store):
    long = store.add_schedule(name="a" * 60, days=[0], start="09:00",
                              end="10:00", categories=["streaming"])
    store.save_schedules([long])
    store.save_schedules([])

    raw = store.schedules_path.read_text(encoding="utf-8")
    assert json.loads(raw) == []
    assert list(store.schedules_path.parent.glob("*.tmp")) == []


def test_schedule_from_dict_requires_id():
    with pytest.raises(ScheduleValidationError):
        schedule_from_dict({"name": "", "days": [0], "start": "09:00",
                            "end": "10:00", "categories": ["streaming"]})


def test_schedule_from_dict_normalises():
    schedule = schedule_from_dict({**VALID, "id": "abcd1234"})
    assert schedule == Schedule(
        id="abcd1234",
        name="Weekday evenings",
        days=[0, 1, 3],
        start="17:00",
        end="19:00",
        categories=["streaming", "gaming"],
    )


def test_schedule_dataclass_round_trips_through_dict():
    schedule = Schedule("abcd1234", "x", [0], "09:00", "10:00", ["gaming"])
    assert schedule_from_dict(schedule.__dict__) == schedule
