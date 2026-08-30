import asyncio
from datetime import datetime
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.categories import ALL_GROUPS
from app.pihole import (
    PiHoleAPIError,
    PiHoleResponseError,
    PiHoleUnavailableError,
)
from app.schedule_store import SchedulerState

client = TestClient(main.app)

MONDAY = datetime(2026, 8, 31)


@pytest.fixture(autouse=True)
def clean_schedule_store():
    def wipe():
        for path in (main.store.schedules_path, main.store.state_path):
            try:
                path.unlink()
            except OSError:
                pass
        main.tick_error = None

    wipe()
    yield
    wipe()


def fixed_now(moment):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment

    return mock.patch.object(main, "datetime", FixedDatetime)


def seed_schedule(**overrides):
    fields = {
        "name": "Weekday evenings",
        "days": [0, 1, 2, 3, 4],
        "start": "17:00",
        "end": "19:00",
        "categories": ["streaming", "gaming"],
    }
    fields.update(overrides)
    return main.store.add_schedule(**fields)

ALL_STATES = {
    "Default": False,
    "streaming": True,
    "gaming": False,
    "social-media": False,
    "orla": True,
    "finnian": False,
    "kian": False,
}


def make_groups(states, comments=None):
    comments = comments or {}
    return {
        "groups": [
            {
                "id": index,
                "name": name,
                "enabled": enabled,
                "comment": comments.get(name),
            }
            for index, (name, enabled) in enumerate(states.items())
        ]
    }


def patch_pihole(get_groups=None, replace_group=None):
    return (
        mock.patch.object(
            main.pihole,
            "get_groups",
            new=mock.AsyncMock(return_value=make_groups(ALL_STATES))
            if get_groups is None
            else get_groups,
        ),
        mock.patch.object(
            main.pihole,
            "replace_group",
            new=replace_group
            if replace_group is not None
            else mock.AsyncMock(),
        ),
    )


def row_state(view, section, key):
    for row in view[section]:
        if row["key"] == key:
            return row["state"]
    raise AssertionError(f"row not found: {section}/{key}")


def captured_context():
    original = main.templates.TemplateResponse
    calls = []

    def capture(*args, **kwargs):
        calls.append(kwargs)
        return original(*args, **kwargs)

    return mock.patch.object(
        main.templates, "TemplateResponse", side_effect=capture
    ), calls


def test_home_builds_view_from_groups():
    context_patch, calls = captured_context()
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch, context_patch:
        response = client.get("/")

    assert response.status_code == 200
    context = calls[0]["context"]
    assert context["error"] is None
    view = context["view"]
    assert [row["key"] for row in view["categories"]] == [
        "streaming",
        "gaming",
        "social-media",
    ]
    assert [row["key"] for row in view["children"]] == [
        "orla",
        "finnian",
        "kian",
    ]
    assert row_state(view, "categories", "streaming") == "BLOCKED"
    assert row_state(view, "categories", "gaming") == "ALLOWED"
    assert row_state(view, "children", "orla") == "BLOCKED"
    assert row_state(view, "children", "kian") == "ALLOWED"
    assert view["all"]["state"] == "MIXED"


def test_home_renders_section_labels_and_child_states():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    for label in ("Content", "Children", "Streaming", "Gaming",
                  "Social Media", "Orla", "Finnian", "Kian"):
        assert label in response.text
    assert "Restrictions ON" in response.text
    assert "Restrictions OFF" in response.text


def test_home_shows_missing_group_hints():
    states = {name: False for name in ALL_STATES if name != "gaming"}
    get_patch, replace_patch = patch_pihole(
        get_groups=mock.AsyncMock(return_value=make_groups(states))
    )

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    assert "MISSING" in response.text
    assert "Create the gaming group in Pi-hole first." in response.text


@pytest.mark.parametrize(
    "error",
    [
        PiHoleUnavailableError("Could not reach Pi-hole at http://x."),
        PiHoleAPIError("Pi-hole API error: HTTP 500."),
        PiHoleResponseError("Pi-hole returned an unexpected response."),
    ],
)
def test_home_shows_error_banner_when_pihole_fails(error):
    get_patch, replace_patch = patch_pihole(
        get_groups=mock.AsyncMock(side_effect=error)
    )

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    assert str(error) in response.text
    assert "Streaming" not in response.text


def test_api_groups_returns_view_json():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.get("/api/groups")

    assert response.status_code == 200
    body = response.json()
    assert [row["key"] for row in body["categories"]] == [
        "streaming",
        "gaming",
        "social-media",
    ]
    assert [row["key"] for row in body["children"]] == [
        "orla",
        "finnian",
        "kian",
    ]
    assert row_state(body, "categories", "streaming") == "BLOCKED"
    assert body["all"]["state"] == "MIXED"


def test_api_groups_returns_502_when_pihole_fails():
    get_patch, replace_patch = patch_pihole(
        get_groups=mock.AsyncMock(
            side_effect=PiHoleUnavailableError("Could not reach Pi-hole.")
        )
    )

    with get_patch, replace_patch:
        response = client.get("/api/groups")

    assert response.status_code == 502
    assert "Could not reach Pi-hole." in response.json()["error"]


def test_category_blocked_enables_only_that_group():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post(
            "/categories/streaming", json={"state": "BLOCKED"}
        )

    assert response.status_code == 200
    replace.assert_awaited_once_with("streaming", None, True)


def test_category_allowed_disables_only_that_group():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post(
            "/categories/social-media", json={"state": "ALLOWED"}
        )

    assert response.status_code == 200
    replace.assert_awaited_once_with("social-media", None, False)


def test_category_toggle_echoes_fetched_comment():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(
        get_groups=mock.AsyncMock(
            return_value=make_groups(ALL_STATES, {"gaming": "games"})
        ),
        replace_group=replace,
    )

    with get_patch, replace_patch:
        response = client.post("/categories/gaming", json={"state": "BLOCKED"})

    assert response.status_code == 200
    replace.assert_awaited_once_with("gaming", "games", True)


def test_child_blocked_enables_only_that_group():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post("/people/orla", json={"state": "BLOCKED"})

    assert response.status_code == 200
    replace.assert_awaited_once_with("orla", None, True)


def test_child_allowed_disables_only_that_group():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post("/people/kian", json={"state": "ALLOWED"})

    assert response.status_code == 200
    replace.assert_awaited_once_with("kian", None, False)


@pytest.mark.parametrize(
    "url",
    [
        "/categories/nope",
        "/people/nobody",
    ],
)
def test_unknown_key_returns_404(url):
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post(url, json={"state": "BLOCKED"})

    assert response.status_code == 404


@pytest.mark.parametrize("url", ["/categories/streaming", "/people/orla"])
def test_invalid_state_body_returns_422(url):
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post(url, json={"state": "MAYBE"})

    assert response.status_code == 422


def test_missing_group_does_not_put_and_names_group():
    states = {name: enabled for name, enabled in ALL_STATES.items()
              if name != "gaming"}
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(
        get_groups=mock.AsyncMock(return_value=make_groups(states)),
        replace_group=replace,
    )

    with get_patch, replace_patch:
        response = client.post("/categories/gaming", json={"state": "BLOCKED"})

    assert response.status_code == 200
    assert "gaming do not exist" in response.text
    assert "Create them in Pi-hole first." in response.text
    replace.assert_not_awaited()


def test_all_blocked_sets_every_group_in_order():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post("/all", json={"state": "BLOCKED"})

    assert response.status_code == 200
    assert [call.args for call in replace.await_args_list] == [
        (name, None, True) for name in ALL_GROUPS
    ]


def test_all_allowed_disables_every_group():
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post("/all", json={"state": "ALLOWED"})

    assert response.status_code == 200
    assert [call.args for call in replace.await_args_list] == [
        (name, None, False) for name in ALL_GROUPS
    ]


def test_all_with_missing_groups_makes_no_changes():
    states = {name: enabled for name, enabled in ALL_STATES.items()
              if name not in ("Default", "kian")}
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(
        get_groups=mock.AsyncMock(return_value=make_groups(states)),
        replace_group=replace,
    )

    with get_patch, replace_patch:
        response = client.post("/all", json={"state": "BLOCKED"})

    assert response.status_code == 200
    assert "Default, kian do not exist" in response.text
    replace.assert_not_awaited()


def test_all_partial_failure_shows_error_banner():
    replace = mock.AsyncMock(
        side_effect=[None, None, PiHoleAPIError("Pi-hole API error: HTTP 500.")]
    )
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post("/all", json={"state": "BLOCKED"})

    assert response.status_code == 200
    assert "Pi-hole API error: HTTP 500." in response.text
    assert "Streaming" not in response.text
    assert replace.await_count == 3


def test_single_toggle_shows_error_when_update_fails():
    replace = mock.AsyncMock(
        side_effect=PiHoleAPIError("Pi-hole API error: HTTP 500.")
    )
    get_patch, replace_patch = patch_pihole(replace_group=replace)

    with get_patch, replace_patch:
        response = client.post(
            "/categories/streaming", json={"state": "BLOCKED"}
        )

    assert response.status_code == 200
    assert "Pi-hole API error: HTTP 500." in response.text
    assert "Streaming" not in response.text


def test_single_toggle_shows_error_when_refetch_fails():
    get = mock.AsyncMock(
        side_effect=[
            make_groups(ALL_STATES),
            PiHoleUnavailableError("Could not reach Pi-hole."),
        ]
    )
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(
        get_groups=get, replace_group=replace
    )

    with get_patch, replace_patch:
        response = client.post(
            "/categories/streaming", json={"state": "BLOCKED"}
        )

    assert response.status_code == 200
    replace.assert_awaited_once_with("streaming", None, True)
    assert "Could not reach Pi-hole." in response.text
    assert "Streaming" not in response.text


SCHEDULE_BODY = {
    "name": "Weekday evenings",
    "days": [0, 1, 2, 3, 4],
    "start": "17:00",
    "end": "19:00",
    "categories": ["streaming", "gaming"],
}


def test_create_schedule_persists_and_renders():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post("/schedules", json=SCHEDULE_BODY)

    assert response.status_code == 200
    assert "Schedule added." in response.text
    assert "Weekday evenings" in response.text
    assert "Weekdays" in response.text
    schedules = main.store.load_schedules()
    assert len(schedules) == 1
    assert schedules[0].id
    assert schedules[0].name == "Weekday evenings"
    assert schedules[0].days == [0, 1, 2, 3, 4]
    assert schedules[0].start == "17:00"
    assert schedules[0].end == "19:00"
    assert schedules[0].categories == ["streaming", "gaming"]


def test_create_schedule_normalises_string_days_and_name():
    get_patch, replace_patch = patch_pihole()
    body = {
        "name": "  Weekend late  ",
        "days": ["6", "5"],
        "start": "21:00",
        "end": "08:00",
        "categories": ["gaming", "social-media"],
    }

    with get_patch, replace_patch:
        response = client.post("/schedules", json=body)

    assert response.status_code == 200
    schedule = main.store.load_schedules()[0]
    assert schedule.name == "Weekend late"
    assert schedule.days == [5, 6]
    assert schedule.categories == ["gaming", "social-media"]


def test_create_schedule_invalid_days_returns_422():
    get_patch, replace_patch = patch_pihole()
    body = {**SCHEDULE_BODY, "days": []}

    with get_patch, replace_patch:
        response = client.post("/schedules", json=body)

    assert response.status_code == 422
    assert "days must be a non-empty list" in response.text
    assert main.store.load_schedules() == []


def test_create_schedule_invalid_time_returns_422():
    get_patch, replace_patch = patch_pihole()
    body = {**SCHEDULE_BODY, "start": "24:00"}

    with get_patch, replace_patch:
        response = client.post("/schedules", json=body)

    assert response.status_code == 422
    assert "invalid time" in response.text
    assert main.store.load_schedules() == []


def test_create_schedule_unknown_category_returns_422():
    get_patch, replace_patch = patch_pihole()
    body = {**SCHEDULE_BODY, "categories": ["streaming", "movies"]}

    with get_patch, replace_patch:
        response = client.post("/schedules", json=body)

    assert response.status_code == 422
    assert "categories must be a non-empty list" in response.text
    assert main.store.load_schedules() == []


def test_create_schedule_missing_fields_returns_422():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post(
            "/schedules", json={"start": "17:00", "end": "19:00"}
        )

    assert response.status_code == 422
    assert "Check the schedule form" in response.text
    assert main.store.load_schedules() == []


def test_update_schedule_keeps_id_and_replaces_fields():
    original = seed_schedule()
    get_patch, replace_patch = patch_pihole()
    body = {
        "name": "Renamed",
        "days": [5, 6],
        "start": "21:00",
        "end": "08:00",
        "categories": ["social-media"],
    }

    with get_patch, replace_patch:
        response = client.post(f"/schedules/{original.id}", json=body)

    assert response.status_code == 200
    assert "Schedule updated." in response.text
    loaded = main.store.load_schedules()
    assert [schedule.id for schedule in loaded] == [original.id]
    assert loaded[0].name == "Renamed"
    assert loaded[0].days == [5, 6]
    assert loaded[0].start == "21:00"
    assert loaded[0].end == "08:00"
    assert loaded[0].categories == ["social-media"]


def test_update_unknown_schedule_returns_404():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post("/schedules/nope", json=SCHEDULE_BODY)

    assert response.status_code == 404


def test_delete_schedule_removes_it():
    original = seed_schedule()
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post(f"/schedules/{original.id}/delete")

    assert response.status_code == 200
    assert "Schedule deleted." in response.text
    assert main.store.load_schedules() == []


def test_delete_unknown_schedule_returns_404():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post("/schedules/nope/delete")

    assert response.status_code == 404


def test_pause_and_resume_persist_state():
    seed_schedule()
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.post("/schedule/pause")

    assert response.status_code == 200
    assert "Scheduler paused." in response.text
    assert main.store.load_state().paused is True

    with get_patch, replace_patch:
        response = client.post("/schedule/resume")

    assert response.status_code == 200
    assert "Scheduler resumed." in response.text
    assert main.store.load_state().paused is False


def test_resume_reapplies_missed_window():
    seed_schedule()
    main.store.save_state(
        SchedulerState(
            paused=True,
            last_enforced={
                "streaming": "ALLOWED",
                "gaming": "ALLOWED",
                "social-media": "ALLOWED",
            },
        )
    )
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(replace_group=replace)
    now_patch = fixed_now(MONDAY.replace(hour=18, minute=0))

    with get_patch, replace_patch, now_patch:
        response = client.post("/schedule/resume")

    assert response.status_code == 200
    assert "Scheduler resumed." in response.text
    assert replace.await_args_list == [
        mock.call("streaming", None, True),
        mock.call("gaming", None, True),
    ]
    state = main.store.load_state()
    assert state.paused is False
    assert state.last_enforced["streaming"] == "BLOCKED"
    assert state.last_enforced["gaming"] == "BLOCKED"
    assert state.last_enforced["social-media"] == "ALLOWED"


ALLOWED_STATES = {
    "streaming": "ALLOWED",
    "gaming": "ALLOWED",
    "social-media": "ALLOWED",
}
BLOCKED_STATES = {
    "streaming": "BLOCKED",
    "gaming": "BLOCKED",
    "social-media": "ALLOWED",
}


def run_tick(moment, last_enforced, paused=False, get_groups=None):
    main.store.save_state(
        SchedulerState(paused=paused, last_enforced=dict(last_enforced))
    )
    replace = mock.AsyncMock()
    get_patch, replace_patch = patch_pihole(
        get_groups=get_groups, replace_group=replace
    )
    with get_patch, replace_patch:
        asyncio.run(main.scheduler_tick(now=moment))
    return replace


def test_scheduler_tick_blocks_categories_at_window_start():
    seed_schedule()
    replace = run_tick(MONDAY.replace(hour=18, minute=0), ALLOWED_STATES)

    assert replace.await_args_list == [
        mock.call("streaming", None, True),
        mock.call("gaming", None, True),
    ]
    state = main.store.load_state()
    assert state.last_enforced["streaming"] == "BLOCKED"
    assert state.last_enforced["gaming"] == "BLOCKED"
    assert state.last_enforced["social-media"] == "ALLOWED"
    assert main.tick_error is None


def test_scheduler_tick_releases_categories_at_window_end():
    seed_schedule()
    replace = run_tick(MONDAY.replace(hour=19, minute=30), BLOCKED_STATES)

    assert replace.await_args_list == [
        mock.call("streaming", None, False),
        mock.call("gaming", None, False),
    ]
    assert (
        main.store.load_state().last_enforced["streaming"]
        == "ALLOWED"
    )
    assert main.tick_error is None


def test_scheduler_tick_does_nothing_when_in_sync():
    seed_schedule()
    replace = run_tick(MONDAY.replace(hour=18, minute=0), BLOCKED_STATES)

    replace.assert_not_awaited()
    assert (
        main.store.load_state().last_enforced["streaming"] == "BLOCKED"
    )
    assert main.tick_error is None


def test_scheduler_tick_skips_everything_while_paused():
    seed_schedule()
    replace = run_tick(
        MONDAY.replace(hour=18, minute=0), ALLOWED_STATES, paused=True
    )

    replace.assert_not_awaited()
    assert main.store.load_state().paused is True
    assert main.store.load_state().last_enforced == ALLOWED_STATES
    assert main.tick_error is None


def test_scheduler_tick_keeps_last_enforced_when_pihole_unreachable():
    seed_schedule()
    get = mock.AsyncMock(
        side_effect=PiHoleUnavailableError("Could not reach Pi-hole.")
    )
    replace = run_tick(
        MONDAY.replace(hour=18, minute=0), ALLOWED_STATES, get_groups=get
    )

    replace.assert_not_awaited()
    assert get.await_count == 1
    assert main.store.load_state().last_enforced == ALLOWED_STATES
    assert main.tick_error == "Could not reach Pi-hole."


def test_scheduler_tick_partial_failure_keeps_previous_state():
    seed_schedule()
    get_patch, replace_patch = patch_pihole(
        replace_group=mock.AsyncMock(
            side_effect=[None, PiHoleAPIError("Pi-hole API error: HTTP 500.")]
        )
    )
    main.store.save_state(SchedulerState(last_enforced=dict(ALLOWED_STATES)))

    with get_patch, replace_patch:
        asyncio.run(
            main.scheduler_tick(now=MONDAY.replace(hour=18, minute=0))
        )

    assert main.store.load_state().last_enforced == ALLOWED_STATES
    assert main.tick_error == "Pi-hole API error: HTTP 500."


def flat(response):
    return " ".join(response.text.split())


def test_dashboard_shows_paused_banner_and_resume_button():
    seed_schedule()
    main.store.save_state(SchedulerState(paused=True))
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    assert "Scheduler paused" in flat(response)
    assert "Resume scheduler" in flat(response)
    assert "Pause scheduler" not in flat(response)


def test_dashboard_shows_tick_error_while_running():
    main.tick_error = "The scheduler hit an unexpected error and will retry."
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    assert (
        "The scheduler hit an unexpected error and will retry."
        in flat(response)
    )


def test_dashboard_hides_tick_error_while_paused():
    main.tick_error = "The scheduler hit an unexpected error and will retry."
    main.store.save_state(SchedulerState(paused=True))
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    assert "unexpected error" not in flat(response)


def test_dashboard_shows_now_line_next_change_and_list():
    seed_schedule()
    get_patch, replace_patch = patch_pihole()
    now_patch = fixed_now(MONDAY.replace(hour=18, minute=0))

    with get_patch, replace_patch, now_patch:
        response = client.get("/")

    assert response.status_code == 200
    text = flat(response)
    assert "Mon 18:00 —" in text
    assert "Streaming: blocked until 19:00" in text
    assert "Gaming: blocked until 19:00" in text
    assert "Social Media: open" in text
    assert "Next change: today 19:00 (in 1h)" in text
    assert "Gaming: blocked to allowed" in text
    assert "Streaming: blocked to allowed" in text
    assert "Weekday evenings" in text
    assert "17:00–19:00" in text
    assert "Streaming, Gaming" in text
    assert "editSchedule" in response.text
    assert 'class="active"' in response.text
    assert "Pause scheduler" in text


def test_dashboard_marks_override_and_scheduled_sublabels():
    seed_schedule()
    get_patch, replace_patch = patch_pihole()
    now_patch = fixed_now(MONDAY.replace(hour=18, minute=0))

    with get_patch, replace_patch, now_patch:
        response = client.get("/")

    text = flat(response)
    assert "override — schedule says blocked until 19:00" in text
    assert "scheduled — blocked until 19:00" in text
    assert text.count("overridden") == 1


def test_dashboard_marks_manual_override_without_schedules():
    get_patch, replace_patch = patch_pihole()

    with get_patch, replace_patch:
        response = client.get("/")

    assert response.status_code == 200
    text = flat(response)
    assert "override — schedule says allowed" in text
    assert text.count("overridden") == 1
    assert "No schedules yet." in text
