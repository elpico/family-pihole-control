from datetime import datetime, time, timedelta

from app.scheduler import (
    Schedule,
    active_end,
    describe_days,
    describe_schedule,
    describe_when,
    format_duration,
    is_active,
    next_change,
    parse_time,
    scheduled_states,
)

MONDAY = datetime(2026, 8, 31)


def make_schedule(**overrides):
    fields = {
        "id": "test",
        "name": "",
        "days": [0],
        "start": "09:00",
        "end": "17:00",
        "categories": ["streaming"],
    }
    fields.update(overrides)
    return Schedule(**fields)


def test_parse_time_accepts_valid_values():
    assert parse_time("00:00") == time(0, 0)
    assert parse_time("09:05") == time(9, 5)
    assert parse_time("23:59") == time(23, 59)


def test_parse_time_rejects_invalid_values():
    for value in ("9:00", "24:00", "12:60", "abcd", "", None, 900):
        try:
            parse_time(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid time {value!r}")


def test_is_active_inside_normal_window():
    schedule = make_schedule()
    assert not is_active(schedule, MONDAY.replace(hour=8, minute=59))
    assert is_active(schedule, MONDAY.replace(hour=9, minute=0))
    assert is_active(schedule, MONDAY.replace(hour=12, minute=30))
    assert not is_active(schedule, MONDAY.replace(hour=17, minute=0))
    assert not is_active(
        schedule, MONDAY.replace(hour=12, minute=30, day=30)
    )
    assert not is_active(schedule, MONDAY.replace(hour=12, minute=30, day=1))


def test_is_active_overnight_window():
    schedule = make_schedule(days=[4], start="21:00", end="08:00")
    friday = MONDAY.replace(day=28)
    saturday = MONDAY.replace(day=29)
    assert not is_active(schedule, friday.replace(hour=20, minute=59))
    assert is_active(schedule, friday.replace(hour=21, minute=0))
    assert is_active(schedule, saturday.replace(hour=7, minute=59))
    assert not is_active(schedule, saturday.replace(hour=8, minute=0))
    assert not is_active(schedule, saturday.replace(hour=12, minute=0))
    assert not is_active(schedule, friday.replace(hour=12, minute=0))


def test_is_active_all_day_when_start_equals_end():
    schedule = make_schedule(start="18:00", end="18:00")
    tuesday = MONDAY + timedelta(days=1)
    assert not is_active(schedule, MONDAY.replace(hour=17, minute=59))
    assert is_active(schedule, MONDAY.replace(hour=18, minute=0))
    assert is_active(schedule, MONDAY.replace(hour=23, minute=59))
    assert is_active(schedule, tuesday.replace(hour=0, minute=1))
    assert is_active(schedule, tuesday.replace(hour=17, minute=59))
    assert not is_active(schedule, tuesday.replace(hour=18, minute=0))


def test_is_active_with_multiple_days():
    schedule = make_schedule(days=[0, 5], start="09:00", end="10:00")
    assert is_active(schedule, MONDAY.replace(hour=9, minute=30))
    assert is_active(schedule, MONDAY.replace(hour=9, minute=30, day=29))
    assert not is_active(schedule, MONDAY.replace(hour=9, minute=30, day=30))


def test_scheduled_states_without_schedules_allows_everything():
    assert scheduled_states([], MONDAY) == {
        "streaming": "ALLOWED",
        "gaming": "ALLOWED",
        "social-media": "ALLOWED",
    }


def test_scheduled_states_blocks_only_active_schedule_categories():
    schedule = make_schedule(categories=["streaming", "gaming"])
    states = scheduled_states([schedule], MONDAY.replace(hour=12))
    assert states["streaming"] == "BLOCKED"
    assert states["gaming"] == "BLOCKED"
    assert states["social-media"] == "ALLOWED"


def test_scheduled_states_unions_overlapping_schedules():
    first = make_schedule(start="09:00", end="12:00", categories=["streaming"])
    second = make_schedule(start="11:00", end="17:00", categories=["gaming"])
    states = scheduled_states([first, second], MONDAY.replace(hour=11, minute=30))
    assert states["streaming"] == "BLOCKED"
    assert states["gaming"] == "BLOCKED"
    states = scheduled_states([first, second], MONDAY.replace(hour=13))
    assert states["streaming"] == "ALLOWED"
    assert states["gaming"] == "BLOCKED"


def test_active_end_is_none_when_category_not_active():
    schedule = make_schedule(categories=["gaming"])
    assert active_end([schedule], MONDAY.replace(hour=12), "streaming") is None


def test_active_end_is_window_end():
    schedule = make_schedule()
    end = active_end([schedule], MONDAY.replace(hour=12), "streaming")
    assert end == MONDAY.replace(hour=17)


def test_active_end_prefers_earliest_of_overlapping_schedules():
    first = make_schedule(start="09:00", end="17:00")
    second = make_schedule(start="10:00", end="12:00")
    end = active_end([first, second], MONDAY.replace(hour=11), "streaming")
    assert end == MONDAY.replace(hour=12)


def test_active_end_for_overnight_window_is_next_day():
    schedule = make_schedule(days=[4], start="21:00", end="08:00")
    saturday = MONDAY.replace(day=29)
    end = active_end([schedule], saturday.replace(hour=7), "streaming")
    assert end == saturday.replace(hour=8)


def test_next_change_upcoming_window_start():
    schedule = make_schedule()
    when, changes = next_change([schedule], MONDAY.replace(hour=8))
    assert when == MONDAY.replace(hour=9)
    assert changes == {"streaming": ("ALLOWED", "BLOCKED")}


def test_next_change_inside_window_is_window_end():
    schedule = make_schedule()
    when, changes = next_change([schedule], MONDAY.replace(hour=12))
    assert when == MONDAY.replace(hour=17)
    assert changes == {"streaming": ("BLOCKED", "ALLOWED")}


def test_next_change_overnight():
    schedule = make_schedule(days=[4], start="21:00", end="08:00")
    friday = MONDAY.replace(day=28)
    saturday = MONDAY.replace(day=29)
    when, changes = next_change([schedule], friday.replace(hour=20))
    assert when == friday.replace(hour=21)
    assert changes == {"streaming": ("ALLOWED", "BLOCKED")}
    when, changes = next_change([schedule], friday.replace(hour=22))
    assert when == saturday.replace(hour=8)
    assert changes == {"streaming": ("BLOCKED", "ALLOWED")}


def test_next_change_skips_to_future_weekday():
    schedule = make_schedule()
    when, _ = next_change([schedule], MONDAY.replace(hour=18))
    assert when == (MONDAY + timedelta(days=7)).replace(hour=9)


def test_next_change_is_none_without_schedules():
    assert next_change([], MONDAY) is None


def test_next_change_reports_no_change_for_back_to_back_schedules():
    first = make_schedule(start="09:00", end="10:00")
    second = make_schedule(start="10:00", end="11:00")
    when, changes = next_change(
        [first, second], MONDAY.replace(hour=9, minute=30)
    )
    assert when == MONDAY.replace(hour=10)
    assert changes == {}


def test_describe_days():
    assert describe_days([0, 1, 2, 3, 4]) == "Weekdays"
    assert describe_days([5, 6]) == "Weekends"
    assert describe_days([0, 1, 2, 3, 4, 5, 6]) == "Every day"
    assert describe_days([0, 1, 2, 3, 4, 5]) == "Mon–Sat"
    assert describe_days([1, 3, 5]) == "Tue, Thu, Sat"
    assert describe_days([2]) == "Wed"
    assert describe_days([4, 0, 2]) == "Mon, Wed, Fri"


def test_describe_schedule_prefers_name():
    named = make_schedule(name="Weekday evenings")
    assert describe_schedule(named) == "Weekday evenings"
    unnamed = make_schedule(days=[0, 1, 2, 3, 4], start="17:00", end="19:00")
    assert describe_schedule(unnamed) == "Weekdays 17:00–19:00"


def test_describe_when():
    now = MONDAY.replace(hour=12)
    assert describe_when(now, now) == "today"
    assert describe_when(now + timedelta(days=1), now) == "tomorrow"
    assert describe_when(now + timedelta(days=2), now) == "Wed"


def test_format_duration():
    assert format_duration(timedelta(seconds=90)) == "1m"
    assert format_duration(timedelta(0)) == "0m"
    assert format_duration(timedelta(seconds=3661)) == "1h 1m"
    assert format_duration(timedelta(days=1, seconds=3661)) == "1d 1h 1m"
