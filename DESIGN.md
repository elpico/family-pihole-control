# Family Pi-hole Control — Design

## 1. Purpose

Family Pi-hole Control is a small local web application that provides a simple UI for controlling an existing Pi-hole installation.

The application does not implement its own DNS filtering or policy engine.

**Pi-hole remains responsible for clients, groups, rules and DNS enforcement.**

Family Pi-hole Control provides a convenient way to enable or disable selected Pi-hole groups.

---

## 2. Scope

The UI provides three levels of control:

### All

Apply a control to everyone.

### Categories

- Streaming
- Gaming
- Social Media

### Children

- Orla
- Finnian
- Kian

The application controls these through the corresponding existing Pi-hole groups.

| UI | Pi-hole group |
|---|---|
| Streaming | `streaming` |
| Gaming | `gaming` |
| Social Media | `social-media` |
| Orla | `orla` |
| Finnian | `finnian` |
| Kian | `kian` |

The application should identify groups by name rather than relying on hard-coded Pi-hole group IDs.

---

## 3. What Pi-hole Owns

Pi-hole remains the source of truth for:

- Clients/devices
- Client-to-group assignments
- Domain and regex rules
- Rule-to-group assignments
- Group enabled/disabled state
- DNS filtering and enforcement

Family Pi-hole Control should not duplicate this information.

The application does **not** manage individual domains or regex rules.

---

## 4. How Control Works

The basic operation is:

```text
User clicks Block/Allow
        ↓
Family Control identifies Pi-hole group
        ↓
Family Control changes group enabled state
        ↓
Pi-hole applies its existing rules
        ↓
DNS requests are blocked or allowed
```

For example:

```text
Streaming → Block
```

means:

```text
Pi-hole group "streaming"
enabled = true
```

and:

```text
Streaming → Allow
```

means:

```text
Pi-hole group "streaming"
enabled = false
```

The same mechanism applies to the child groups.

---

## 5. All Control

The UI should provide an **All** control for applying a restriction across everyone.

The exact implementation of All should remain isolated from the normal single-group controls.

`Default` is a special built-in Pi-hole group and should not automatically be assumed to represent the same thing as "All".

The application should determine the appropriate set of groups to modify for an All operation and apply the change consistently.

This logic should be kept in one place so it can be changed later without affecting category or child controls.

---

## 6. UI

The UI should remain deliberately simple.

A possible layout:

```text
FAMILY CONTROL

ALL
────────────────────────────────
[ Block All ]          [ Allow All ]


CONTENT
────────────────────────────────
Streaming       BLOCKED       [ Allow ]
Gaming          ALLOWED       [ Block ]
Social Media    ALLOWED       [ Block ]


CHILDREN
────────────────────────────────
Orla            BLOCKED       [ Allow ]
Finnian         ALLOWED       [ Block ]
Kian            ALLOWED       [ Block ]
```

The displayed state comes from the corresponding Pi-hole group.

### State terminology

When a restriction group is enabled:

```text
BLOCKED
```

When a restriction group is disabled:

```text
ALLOWED
```

The UI should make the current state obvious and provide the opposite action.

---

## 7. Pi-hole API

Use the Pi-hole v6 API.

The application needs only the functionality required to:

1. Read groups.
2. Find the configured groups by name.
3. Read their enabled state.
4. Change a group's enabled state.
5. Confirm the resulting state.

The exact API endpoint and payload should be based on the installed Pi-hole API rather than assumptions about earlier Pi-hole versions.

Do not modify Pi-hole's database directly.

---

## 8. Application Structure

Keep the application small.

A suitable structure is:

```text
app/
├── __init__.py
├── main.py
├── pihole.py
└── templates/
    └── index.html
```

The Pi-hole client should contain the API interaction.

The FastAPI application should contain the routes and UI behaviour.

Avoid introducing additional layers unless they solve a real problem.

---

## 9. Configuration

The application should have a small configuration describing the groups exposed by the UI.

For example:

```python
GROUPS = {
    "categories": {
        "streaming": "Streaming",
        "gaming": "Gaming",
        "social-media": "Social Media",
    },
    "children": {
        "orla": "Orla",
        "finnian": "Finnian",
        "kian": "Kian",
    },
}
```

These names identify existing Pi-hole groups.

The application should not create missing groups automatically.

If a configured group does not exist, the application should report a clear error.

---

## 10. API Routes

Keep the application API small.

Conceptually:

```text
GET  /
GET  /api/groups
POST /categories/{group}
POST /children/{group}
POST /all
```

The exact route structure can be simplified if a common route is preferable.

The important requirement is that category and child operations ultimately change the enabled state of the corresponding Pi-hole group.

---

## 11. Error Handling

The application should handle:

- Pi-hole unavailable
- Pi-hole API errors
- Configured group not found
- Invalid API responses
- Failed group updates

A failed operation should not be presented to the user as successful.

The UI should retain or refresh the actual state reported by Pi-hole.

---

## 12. Security and Deployment

The application is intended for use on the local network.

Pi-hole credentials and other secrets must not be committed to Git.

Use environment variables for configuration and credentials where required.

The application should not expose Pi-hole's API directly to the Internet.

Docker Compose is the intended deployment mechanism.

---

## 13. Explicitly Out of Scope

The following are deliberately **not part of the current application**:

- Individual service controls
- Individual domain controls
- Regex editing
- Domain management
- Client/device management
- Creating or deleting Pi-hole groups
- Creating or deleting Pi-hole rules
- Editing client-to-group assignments
- Editing rule-to-group assignments
- User accounts
- Audit history
- Application database
- Remote access
- A second DNS or policy engine

If a future requirement needs one of these, it should be considered separately rather than added speculatively.

---

## 14. Design Principles

1. **Keep it simple.**
2. **Pi-hole is the source of truth.**
3. **Pi-hole is the enforcement engine.**
4. **Groups are the control surface.**
5. **Do not manipulate individual domain rules.**
6. **Do not duplicate Pi-hole configuration.**
7. **Do not introduce a database without a concrete requirement.**
8. **The UI should expose family-friendly controls, not Pi-hole implementation details.**
9. **Use the existing Pi-hole group structure rather than creating another policy model.**
10. **Prefer a small amount of reliable functionality over a feature-rich architecture.**

---

## 15. MVP Success Criteria

The MVP is successful when the user can open Family Pi-hole Control and:

- See the current state of Streaming, Gaming and Social Media.
- See the current state of Orla, Finnian and Kian.
- Block or allow each category.
- Block or allow each child.
- Apply an All operation.
- See the resulting state reflected from Pi-hole.
- Verify that the resulting DNS behaviour is enforced by Pi-hole.

The application should accomplish this without reading, modifying or maintaining individual Pi-hole domain/regex rules.

**Family Pi-hole Control is a simple control panel for Pi-hole groups — nothing more.**

---

## 16. Scheduling (weekly internet control)

The application includes a simple weekly scheduler for the three content
category groups (`streaming`, `gaming`, `social-media`). Child groups and
`Default` remain manual-only.

### Model

A schedule has an optional name, a set of days (0–6, Monday = 0), a start
time and an end time (server-local `HH:MM`), and the categories to block.

- Window end = auto-allow: a category is BLOCKED iff at least one active
  schedule includes it, ALLOWED otherwise. The scheduler enforces both
  directions.
- If `end < start`, the window runs overnight (e.g. Fri 21:00 → Sat 08:00).
- If `end == start`, the window covers the full 24h day.
- Weekday/weekend differences are just schedules with different day sets
  (quick-picks in the form). No calendar UI.

### Enforcement

A single asyncio task (stdlib only — no APScheduler) started in the
FastAPI lifespan ticks every `$SCHEDULER_TICK_SECONDS` (default 30) and
sleeps before the first tick. Each tick:

1. If paused, do nothing.
2. Compute the scheduled state per category at the current time.
3. For each category whose scheduled state differs from the last enforced
   state, change the Pi-hole group via the normal group-update path and
   record it in `last_enforced`.

A failed update does not update `last_enforced`, so the change retries on
the next tick and an error is shown on the dashboard. First run (no state
file) initialises `last_enforced` to the current scheduled state without
forcing, so existing Pi-hole state is never clobbered.

### Pause and resume

- While paused the scheduler never touches groups; manual Allow/Block
  toggles persist indefinitely.
- Resuming immediately re-applies the current scheduled state (catch-up).
- While unpaused, a manual toggle sticks until the next boundary, where
  the schedule re-asserts.

### Persistence

Two JSON files in `$SCHEDULE_DIR` (default `./data`, `/data` in Docker):

- `schedules.json` — schedule definitions.
- `scheduler-state.json` — `{paused, last_enforced}`.

Writes are atomic (tmp file + rename); missing or corrupt files fall back
to empty defaults so the app never crashes on startup. No database.

### Time

All times are server-local (the machine running the app). There is no
timezone picker.