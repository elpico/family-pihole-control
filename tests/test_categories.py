from app.categories import (
    ALL_GROUPS,
    CATEGORIES,
    KIDS,
    all_state,
    build_view,
    group_state,
)


def make_group(name, enabled, group_id):
    return {"id": group_id, "name": name, "enabled": enabled, "comment": None}


def by_name(groups):
    return {group["name"]: group for group in groups}


def row_state(view, section, key):
    for row in view[section]:
        if row["key"] == key:
            return row["state"]
    raise AssertionError(f"row not found: {section}/{key}")


ALL_GROUPS_PRESENT = {
    name: make_group(name, enabled, index)
    for index, (name, enabled) in enumerate(
        [
            ("Default", False),
            ("streaming", True),
            ("gaming", False),
            ("social-media", False),
            ("orla", True),
            ("finnian", False),
            ("kian", False),
        ]
    )
}


def test_categories_are_the_three_content_groups():
    assert CATEGORIES == {
        "streaming": "Streaming",
        "gaming": "Gaming",
        "social-media": "Social Media",
    }


def test_children_are_the_three_child_groups():
    assert KIDS == {"orla": "Orla", "finnian": "Finnian", "kian": "Kian"}


def test_all_groups_covers_default_plus_categories_plus_children():
    assert ALL_GROUPS == (
        "Default",
        "streaming",
        "gaming",
        "social-media",
        "orla",
        "finnian",
        "kian",
    )


def test_group_state_maps_enabled_to_blocked():
    assert group_state(make_group("streaming", True, 1)) == "BLOCKED"


def test_group_state_maps_disabled_to_allowed():
    assert group_state(make_group("streaming", False, 1)) == "ALLOWED"


def test_group_state_maps_absent_group_to_missing():
    assert group_state(None) == "MISSING"


def test_all_state_blocked_when_every_group_enabled():
    states = {name: True for name in ALL_GROUPS}
    assert all_state(by_name([make_group(n, s, i) for i, (n, s) in enumerate(states.items())])) == "BLOCKED"


def test_all_state_allowed_when_no_group_enabled():
    assert all_state(by_name([make_group(n, False, i) for i, n in enumerate(ALL_GROUPS)])) == "ALLOWED"


def test_all_state_mixed_when_only_some_groups_enabled():
    assert all_state(by_name(list(ALL_GROUPS_PRESENT.values()))) == "MIXED"


def test_all_state_missing_when_any_group_absent_even_if_rest_uniform():
    groups = [
        make_group(name, True, index)
        for index, name in enumerate(ALL_GROUPS)
        if name != "Default"
    ]
    assert all_state(by_name(groups)) == "MISSING"


def test_build_view_lists_categories_and_children_in_config_order():
    view = build_view(list(ALL_GROUPS_PRESENT.values()))

    assert [row["key"] for row in view["categories"]] == [
        "streaming",
        "gaming",
        "social-media",
    ]
    assert [row["name"] for row in view["categories"]] == [
        "Streaming",
        "Gaming",
        "Social Media",
    ]
    assert [row["key"] for row in view["children"]] == [
        "orla",
        "finnian",
        "kian",
    ]
    assert [row["name"] for row in view["children"]] == [
        "Orla",
        "Finnian",
        "Kian",
    ]


def test_build_view_row_states_come_from_group_enabled():
    view = build_view(list(ALL_GROUPS_PRESENT.values()))

    assert row_state(view, "categories", "streaming") == "BLOCKED"
    assert row_state(view, "categories", "gaming") == "ALLOWED"
    assert row_state(view, "children", "orla") == "BLOCKED"
    assert row_state(view, "children", "kian") == "ALLOWED"
    assert view["all"]["state"] == "MIXED"


def test_build_view_marks_absent_groups_missing():
    groups = [
        group
        for group in ALL_GROUPS_PRESENT.values()
        if group["name"] != "gaming"
    ]
    view = build_view(groups)

    assert row_state(view, "categories", "gaming") == "MISSING"
    assert row_state(view, "categories", "streaming") == "BLOCKED"
    assert view["all"]["state"] == "MISSING"
