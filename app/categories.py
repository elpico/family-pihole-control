CATEGORIES = {
    "streaming": "Streaming",
    "gaming": "Gaming",
    "social-media": "Social Media",
}

KIDS = {
    "orla": "Orla",
    "finnian": "Finnian",
    "kian": "Kian",
}

ALL_GROUPS = ("Default", *CATEGORIES, *KIDS)


def group_state(group):
    if group is None:
        return "MISSING"
    return "BLOCKED" if group["enabled"] else "ALLOWED"


def all_state(groups_by_name):
    enabled = []
    for name in ALL_GROUPS:
        group = groups_by_name.get(name)
        if group is None:
            return "MISSING"
        enabled.append(group["enabled"])
    if all(enabled):
        return "BLOCKED"
    if not any(enabled):
        return "ALLOWED"
    return "MIXED"


def _row(key, label, groups_by_name):
    group = groups_by_name.get(key)
    return {
        "key": key,
        "name": label,
        "state": group_state(group),
        "group": group,
    }


def build_view(groups):
    groups_by_name = {group["name"]: group for group in groups}
    return {
        "categories": [
            _row(key, label, groups_by_name)
            for key, label in CATEGORIES.items()
        ],
        "children": [
            _row(key, label, groups_by_name) for key, label in KIDS.items()
        ],
        "all": {
            "key": "all",
            "name": "All",
            "state": all_state(groups_by_name),
        },
    }
