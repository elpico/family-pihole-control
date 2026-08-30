# MVP Refactor Plan

Status: approved decisions recorded; ready to implement.
Source of truth for design: `DESIGN.md` (single file — no split into separate MVP docs).

## Decisions (confirmed 2026-08-25)

1. **Dashboard shows categories only.** Remove the Pi-hole group list from the UI.
   `get_groups()` stays in the client for later use.
2. **Strict BLOCKED/ALLOWED states.** A category is BLOCKED if any of its rules is
   enabled, ALLOWED if none are. No PARTIAL state. Toggling a category sets ALL of
   its rules to the target state.
3. **Single `DESIGN.md`.** No `DESIGN_MVP.md` / `SERVICE_DESIGN_MVP.md` split.

## Live API validation (read-only, done against 192.168.1.115)

- `GET /api/domains` returns all rules:
  `{id, domain, unicode, type (deny/allow), kind (exact/regex), comment, groups
  (list of group ids), enabled, date_added, date_modified}`.
- Current install: 18 rules, all 9 service comments present, all enabled:
  youtube×7, roblox×3, minecraft×2, iplayer, netflix, primevideo, instagram,
  tiktok, snapchat.
- Update path: `PUT /api/domains/{type}/{kind}/{domain}` ("replace domain").
  Must re-send ALL fields including `comment` and `groups` to preserve them.
  `id`/`date_added` are preserved, `date_modified` auto-updated.
  Regex domains must be URI-escaped in the URL.
- Data quirk: one rule's comment is `"tiktok "` (trailing space). App normalizes
  comments (`strip().lower()`) when matching, and echoes the original comment
  verbatim when updating. Fix the data manually in Pi-hole separately.

## Implementation steps

### 1. (COMPLETED) `app/pihole.py` — refactor + extend 

- Extract the repeated httpx/try/except block into a private
  `_request(method, path, json=None)` helper.
  Keep the four error classes (`PiHoleError`, `PiHoleUnavailableError`,
  `PiHoleAPIError`, `PiHoleResponseError`) and the payload-validation style.
- Add `get_domains()`:
  - `GET /api/domains`
  - Validate shape: dict with `domains` list; each item must be a dict with at
    least `id`, `domain`, `type`, `kind`, `comment`, `groups`, `enabled`.
- Add `replace_domain(rule)`:
  - `PUT /api/domains/{type}/{kind}/{domain}` with `quote()`d domain.
  - Body: the rule unchanged except `enabled` — echo `comment` verbatim
    (preserves the `"tiktok "` quirk) and `groups` as-is.
  - Validate the response contains the updated rule.
- Keep `get_groups()` (no longer rendered in UI, retained for later).

### 2. (COMPLETED) New `app/categories.py`

```text
CATEGORIES (ordered) =
    Streaming:      youtube, iplayer, primevideo, netflix
    Gaming:         roblox, minecraft
    Social Media:   instagram, tiktok, snapchat
```

- `normalize_comment(comment)` → `(comment or "").strip().lower()`.
- `build_categories(domains)` → list of category states, each with:
  - `key` (e.g. `streaming`), `name` (e.g. `Streaming`)
  - `rules` — the matching Pi-hole rules
  - `state` — `"BLOCKED"` if any rule is enabled, else `"ALLOWED"`
- Rules whose normalized comment matches no known category are ignored
  (the app does not manage them).

### 3. (COMPLETED) `app/main.py`

- `GET /`:
  - Call `get_domains()`, build category states, render dashboard.
  - Keep existing error handling pattern (`PiHoleError` → error banner).
- `POST /categories/{key}` (body: target state):
  - Unknown key → 404.
  - For every rule in the category, call `replace_domain()` with
    `enabled = (target == BLOCKED)`; preserve all other fields.
  - Re-fetch domains and re-render so the UI reflects confirmed state.
  - If some rules succeed and others fail, render updated state plus a
    partial-failure message (design §10 Phase 2).

### 4. (COMPLETED) `app/templates/index.html`

- Replace the group list with the category dashboard:
  - `FAMILY CONTROL` heading
  - `CONTENT CATEGORIES` section
  - One row per category: name + BLOCKED/ALLOWED + toggle control
  - HTMX via CDN (design stack: Jinja2 + HTMX); toggle posts to
    `POST /categories/{key}` and swaps in the refreshed dashboard.
- Keep the existing error-banner pattern (`.error` styling).
- Keep it intentionally simple — no per-app rows, no group rows.

### 5. (COMPLETED) Tests

- `tests/test_pihole.py`:
  - `get_domains`: happy path, transport error, HTTP error, invalid JSON,
    unexpected shapes.
  - `replace_domain`: asserts correct PUT URL (incl. URI-escaped regex domain)
    and that `comment` + `groups` are preserved in the payload.
- New `tests/test_categories.py`:
  - Comment → category mapping for all 9 services.
  - Normalization: `"tiktok "`, `"  YouTube "`, `None`.
  - State rules: all enabled → BLOCKED, none → BLOCKED-free ALLOWED,
    any enabled → BLOCKED (strict any-semantics).
  - Unknown comments ignored.
- `tests/test_main.py`:
  - Dashboard renders the 3 categories with correct states.
  - Toggle endpoint flips `enabled` on exactly the category's rules
    (mocked client), other rules untouched.
  - Partial-failure message appears when one rule update fails.
  - Existing error-banner behaviour retained.

## Out of scope (design §11)

Group controls, individual app/service toggles, scheduling, temporary
overrides, device management, user accounts, audit logging, drift detection,
rule creation/deletion, regex/domain editing, remote access, any database.

## Deferred follow-ups (not part of MVP)

- Update `README.md` architecture list (still mentions SQLite/APScheduler as
  "planned"; design says no DB for MVP).
- Manually fix the `"tiktok "` trailing-space comment in Pi-hole.
- `.env.example` lists `PIHOLE_PASSWORD` but the client does not use it yet
  (install has no API password; acceptable for LAN-only MVP).

## V2: group-based control (decisions confirmed 2026-08-27)

Live investigation (192.168.1.115) showed the family enforces access via
**group `enabled`**, not domain-rule `enabled`: all 18 rules report
`enabled: true`, while `kids-restricted` / `Orla-restricted` / `TV` groups
are disabled. The MVP's `replace_domain(enabled=...)` toggles the rule
globally — wrong lever.

### Decisions
1. **One Pi-hole group per kid × category**, named `{kid}-{category}`:
   orla/kian × streaming/gaming/social-media (6 groups:
   `orla-streaming`, `orla-gaming`, `orla-social-media`,
   `kian-streaming`, `kian-gaming`, `kian-social-media`).
2. **Grid UI**: rows = All, Orla, Kian; columns = Streaming, Gaming,
   Social Media. Cell = the kid×category group's `enabled` state.
   - Cell BLOCKED/ALLOWED toggles exactly that group
     (`PUT /api/groups/{name}`, one atomic call).
   - **All row is derived**: BLOCKED only when every kid's group for that
     category is blocked; otherwise ALLOWED. Toggling it fans out to all
     kids' groups for that category.
   - Group absent → cell shows "Not set up" (no button).
3. **`POST /sync-groups`** (dashboard button):
   - creates any missing kid×category groups (`POST /api/groups`,
     initially `enabled: false` so sync never changes effective access),
   - extends every category rule's `groups` array to include all kids'
     group ids for that category (`PUT /api/domains/{type}/{kind}/{domain}`,
     all other fields echoed unchanged),
   - skips rules whose comment maps to no known category,
   - reports `created N group(s), updated M rule(s)`.
   - Idempotent: re-running with everything in place changes nothing.
4. **Old groups** (`kids-restricted`, `Orla-restricted`) are left in place;
   delete them in the Pi-hole UI after the new grid is in use. `TV` is a
   device group, out of scope.

### Implementation (completed 2026-08-27)
- `app/categories.py`: `KIDS`, `group_name()`, `build_grid(groups)`
  (replaces `build_categories`); comment mapping retained for sync.
- `app/pihole.py`: `create_group(name, comment, enabled)` →
  `POST /api/groups`; `replace_group(name, comment, enabled)` →
  `PUT /api/groups/{name}` (both validate the groups payload shape).
- `app/main.py`:
  - `GET /` renders the grid from `GET /api/groups`.
  - `POST /grid/{kid}/{category}` (body `{"state": BLOCKED|ALLOWED}`):
    kid ∈ {orla, kian, all}; unknown kid/category → 404; missing group →
    "Press the Sync groups button first" banner, no mutation.
  - `POST /sync-groups` as decided above.
  - No more `replace_domain(enabled=...)` from toggles; `replace_domain`
    is now used only by sync, and only to extend `groups`.
- `app/templates/index.html`: grid table, per-cell Allow/Block buttons,
  Sync groups button, "Not set up" state, note banner for sync summary.
- Tests: `test_categories.py` (grid state rules incl. All-row derivation
  and MISSING), `test_main.py` (grid rendering, kid/all toggles, missing
  group, 404s, sync create+assign, sync idempotency), `test_pihole.py`
  (create_group/replace_group URLs, bodies, errors).

### Out of scope (still)
Scheduling, temporary overrides, device groups, per-app toggles, user
accounts, audit logging, rule creation/deletion, remote access, any DB.

# V3 Refactor Plan — Flat Pi-hole Groups

## 1. Objective

Refactor the application from the previous service/domain model to the simpler **Pi-hole group model**.

The live Pi-hole configuration has already been reorganised manually.

Family Control should now treat **Pi-hole groups as the control surface**.

The application should:

- Read group state from Pi-hole and use api-spec in /api-spec to query. 
- Display selected groups in the UI.
- Enable/disable those groups.
- Never modify individual Pi-hole domain or regex rules.
- Never manage Pi-hole client membership.
- Keep the UI deliberately simple. 

---

## 2. Live Pi-hole Model

The current Pi-hole contains these relevant groups:

### Categories

```text
streaming
gaming
social-media
```

### Children

```text
orla
finnian
kian
```

### Built-in

```text
Default
```

Pi-hole already contains the required:

- client → group assignments
- rule → group assignments
- domain/regex rules

These are maintained manually in Pi-hole.

Family Control must not attempt to recreate or synchronise them.

---

## 3. UI Scope

The UI has three control scopes.

### All

A bulk control applying the selected restriction state to everyone.

This is a special operation because Pi-hole's `Default` group and the other groups have different roles.

Do not assume that changing only the `Default` group is equivalent to "All".

Keep the All implementation isolated so its exact behaviour can be adjusted independently.

### Content

Three category controls:

```text
Streaming
Gaming
Social Media
```

Each maps directly to the corresponding Pi-hole group.

### Children

Three child controls:

```text
Orla
Finnian
Kian
```

Each maps directly to the corresponding Pi-hole group.

There is deliberately **no per-child/per-category matrix**.

---

## 4. UI Behaviour

Use two main sections:

```text
CONTENT

Streaming       BLOCKED       [Allow]
Gaming          ALLOWED       [Block]
Social Media    ALLOWED       [Block]


CHILDREN

Orla            BLOCKED       [Allow]
Finnian         ALLOWED       [Block]
Kian            ALLOWED       [Block]
```

Also provide the All control separately.

For category groups:

- `enabled=true` → `BLOCKED`
- `enabled=false` → `ALLOWED`

For child groups:

- `enabled=true` → `Restrictions ON`
- `enabled=false` → `Restrictions OFF`

The button should always perform the opposite action.

The displayed state must come from Pi-hole rather than local application state.

---

## 5. Group Mapping

The application needs only a small UI configuration mapping.

Conceptually:

```python
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
```

These are UI labels only.

They are not a second policy definition.

The application must find the corresponding Pi-hole group by name and use the ID/value returned by Pi-hole as appropriate.

Do not hardcode Pi-hole numeric group IDs.

---

## 6. Read Flow

On page load:

```text
GET /
   ↓
GET groups from Pi-hole
   ↓
Find configured category groups
Find configured child groups
   ↓
Read enabled state
   ↓
Render UI
```

The application does **not** need to:

- retrieve domains
- retrieve regex rules
- inspect rule comments
- map services to categories
- inspect domain group assignments
- synchronise rules

---

## 7. Change Flow

For a category or child:

```text
User clicks Block/Allow
        ↓
POST application endpoint
        ↓
Find corresponding Pi-hole group
        ↓
Set group enabled state
        ↓
Confirm resulting state
        ↓
Render/update UI
```

For example:

```text
POST /categories/streaming
{
    "state": "BLOCKED"
}
```

results in the Pi-hole `streaming` group being enabled.

Similarly:

```text
POST /people/orla
{
    "state": "ALLOWED"
}
```

results in the Pi-hole `orla` group being disabled.

The exact Pi-hole API call should use the existing `PiHoleClient` group abstraction.

---

## 8. All Control

All is a bulk operation and should not be implemented by pretending that `Default` alone represents the complete family policy.

The implementation should explicitly define which groups participate in the All operation.

At minimum, the implementation should account for:

```text
Default
streaming
gaming
social-media
orla
finnian
kian
```

Do not change client membership or rule membership.

Do not modify domain rules.

If the correct All semantics are uncertain from the existing Pi-hole configuration, keep the All implementation isolated and make the uncertainty explicit rather than inventing additional policy behaviour.

---

## 9. Pi-hole Client

The Pi-hole client should expose only the functionality required by this application.

Keep:

- group retrieval
- group update
- group validation/error handling

Remove application dependencies on:

- domain retrieval
- domain replacement
- rule synchronisation
- group creation
- client/rule membership management

The application must not write individual Pi-hole domain rules.

---

## 10. Routes

Keep the API small.

A reasonable structure is:

```text
GET  /
GET  /api/groups

POST /categories/{name}
POST /people/{name}
POST /all
```

The exact route names may be adjusted if the existing application has a cleaner convention.

Category and child routes should share the same underlying group-state update logic.

Unknown configured keys should return an appropriate error.

If a configured Pi-hole group does not exist, do not create it automatically.

---

## 11. Missing Groups

If a configured group cannot be found in Pi-hole:

```text
MISSING
```

may be displayed instead of a normal state.

The application must not silently create the group.

The error should be clear enough to indicate that the group needs to exist in Pi-hole.

This should remain lightweight; do not build a group synchronisation system.

---

## 12. Files to Refactor

### `app/categories.py`

Simplify the existing configuration/model to represent:

- three categories
- three children

Remove the old service/comment/domain mapping logic.

Do not replace it with another complex abstraction.

### `app/main.py`

Simplify routes and page rendering.

Remove:

- domain-based category handling
- service/domain synchronisation
- old grid behaviour

Add/use:

- category group controls
- child group controls
- All control
- shared group-state update logic

### `app/pihole.py`

Retain the group API functionality.

Remove functionality that exists only to support the previous domain/rule model.

Do not add new abstractions unless required by the actual Pi-hole API.

### `app/templates/index.html`

Replace the old grid/service UI with:

- All control
- Content section
- Children section

Each row should contain:

- friendly label
- current state
- opposite-state action button

Keep the UI simple.

---

## 13. Tests

Update tests to reflect the group-only architecture.

### Group/configuration tests

Verify:

- three categories exist
- three children exist
- labels are correct
- group state maps correctly:
  - enabled → BLOCKED
  - disabled → ALLOWED
  - missing → MISSING

### Application tests

Verify:

- home page renders categories
- home page renders children
- category BLOCKED request enables the corresponding group
- category ALLOWED request disables the corresponding group
- child BLOCKED request enables the corresponding group
- child ALLOWED request disables the corresponding group
- unknown key is rejected
- missing Pi-hole group does not result in a PUT
- All invokes the intended bulk group behaviour

### Pi-hole tests

Keep tests for:

- reading groups
- updating groups
- group validation
- API error handling

Remove tests whose only purpose was to support the previous domain/rule synchronisation model.

---

## 14. Verification

Run:

```bash
python -m pytest tests/ -q
```

All tests must pass.

Then perform a live smoke test against Pi-hole:

1. Load Family Control.
2. Confirm displayed states match Pi-hole.
3. Toggle one category.
4. Confirm the corresponding Pi-hole group state changes.
5. Test actual DNS behaviour for a client assigned to that category.
6. Toggle the category back.
7. Repeat with one child group.
8. Confirm the child group state and DNS behaviour.
9. Test All only after its intended semantics have been verified.

---

## 15. Explicitly Removed From V2

The following concepts from the previous design are no longer part of Family Control:

- Service catalogue
- YouTube/iPlayer/Netflix/etc. mapping
- Regex/domain discovery
- Rule comments as category metadata
- Domain-level enable/disable
- Domain PUT operations
- `/sync-groups`
- Automatic creation of Pi-hole groups
- Automatic assignment of rules to groups
- Automatic assignment of clients to groups
- Per-child/per-category grid
- `{kid}-{category}` combination groups
- Application-owned policy database

Pi-hole is already responsible for these relationships.

---

## 16. Design Principle

The application should remain a **thin control panel over Pi-hole groups**.

The desired architecture is:

```text
                 Family Control
                       │
                 Simple UI
                       │
                       ▼
                  Pi-hole API
                       │
                       ▼
                    Groups
                       │
             ┌─────────┴─────────┐
             │                   │
         Categories           Children
             │                   │
       Streaming             Orla
       Gaming                Finnian
       Social Media          Kian
             │                   │
             └─────────┬─────────┘
                       ▼
                  Pi-hole rules
                       │
                       ▼
                     DNS
```

Do not introduce additional policy or service abstractions unless a concrete requirement cannot be satisfied by this model.

The goal is a small, reliable family control panel — **not a replacement for Pi-hole's policy management UI.**

## 17. Implementation (V3)

Tasks in order; each is marked complete in this list as it lands.

Live model investigation (192.168.1.115, read-only): 7 groups exist —
`Default`(0), `orla`(2), `streaming`(3), `finnian`(5), `gaming`(6),
`social-media`(7), `kian`(14). Every content rule is assigned to exactly the
three child groups plus one category group (exception: `iplayer` rules are
assigned to `Default` + orla + finnian + kian). No rule references any other
group, so the All operation over
`Default + 3 categories + 3 children` covers every rule.

Working decisions (2026-08-28, from Task 1 session — safe to revisit):

- `POST /all`: BLOCKED → enable every `ALL_GROUPS` group, ALLOWED → disable
  every one. If any configured All group is absent from Pi-hole, no
  mutation happens; render an error naming the missing group(s).
- All displayed state is derived: all enabled → BLOCKED, none enabled →
  ALLOWED, partial → MIXED (no button offered), any group absent → MISSING.
- `POST /categories/{name}` / `POST /people/{name}`: unknown key → 404.
  Configured group absent from Pi-hole → no PUT, render a clear error
  ("create it in Pi-hole"); never auto-create.
- Both single routes and All share one group-update path: find group by
  name, `replace_group(name, comment, enabled)` echoing the fetched comment,
  then re-fetch groups and render from Pi-hole state (no local state).
- `GET /api/groups` returns the built view (category/child/All states) as
  JSON.
- Child rows display "Restrictions ON" (enabled) / "Restrictions OFF"
  (disabled) per §4; button labels stay Allow/Block (opposite action).
- Live DNS note for Task 6: a child's devices are members of their child
  group AND the category groups, so disabling one group may not fully lift
  that child's restrictions. The app only toggles groups and never reasons
  about membership (Pi-hole owns the relationships) — interpret smoke-test
  DNS results with that in mind.

- [x] Task 1: `app/categories.py` — flat UI label maps + group state model (§5, §12)
  - Done: `CATEGORIES`/`KIDS` are plain key→label dicts (incl. `finnian`);
    `ALL_GROUPS` = Default + categories + children; `group_state()`
    (enabled→BLOCKED, disabled→ALLOWED, absent→MISSING); `all_state()`
    (all enabled→BLOCKED, none→ALLOWED, partial→MIXED, any absent→MISSING);
    `build_view(groups)` → flat `categories`/`children`/`all` rows.
    Old comment/domain/grid logic removed. Note: `app/main.py` still imports
    the old names until Task 3, so the app is transitional until then.
- [x] Task 2: `app/pihole.py` — group API only; remove domain/rule functionality (§9, §12)
  - Done: client keeps `get_groups()`, `replace_group()`, `validate_groups()`,
    `_request()` and the four error classes (verified against
    `api-spec/groups.yaml`: GET `/api/groups`, PUT `/api/groups/{name}` with
    `{name, comment, enabled}`, response shape identical to GET). Removed
    `get_domains()`, `replace_domain()`, `create_group()`,
    `validate_domains()`, `validate_replaced_domain()`. Note: `app/main.py`
    still calls the removed methods until Task 3, so the app is transitional
    until then.
- [x] Task 3: `app/main.py` — `GET /`, `GET /api/groups`, `POST /categories/{name}`, `POST /people/{name}`, `POST /all` (§7, §8, §10, §12)
  - Done: `GET /` fetches groups, builds the view, renders the dashboard
    (context: `view`, `error`, `note`); `PiHoleError` → error banner.
    `GET /api/groups` returns the `build_view` result as JSON (502 +
    `{"error": ...}` JSON on `PiHoleError`). `POST /categories/{name}` /
    `POST /people/{name}` (body `{"state": BLOCKED|ALLOWED}`) share
    `set_single_group()`: unknown key → 404; configured group absent from
    Pi-hole → no PUT, render the view plus an error naming the group and
    saying to create it in Pi-hole (never auto-created). `POST /all` stays an
    isolated route (§8): any `ALL_GROUPS` group absent → no mutation, error
    naming the missing group(s); otherwise sets every one of the 7 groups.
    All mutations go through one shared path, `apply_group_states()`:
    `replace_group(name, comment, enabled)` echoing the fetched comment, then
    re-fetch groups and render from Pi-hole state (no local state).
    Grid/sync routes and the old `CellStateUpdate` model removed. Note:
    `app/templates/index.html` and `tests/` still reflect the V2 grid model
    until Tasks 4–5, so the app is transitional until then (smoke-checked:
    view JSON, comment echo, 404s, missing-group no-op, All fan-out,
    error banners).
- [x] Task 4: `app/templates/index.html` — All control, Content section, Children section (§4, §12)
  - Done: full rewrite. `FAMILY CONTROL` heading; `ALL` section with one
    row (state badge; Allow/Block button only for BLOCKED/ALLOWED, hint text
    and no button for MIXED/"set them individually" or
    MISSING/"create them first"); `CONTENT` section with one row per category
    (BLOCKED/ALLOWED badge + opposite-action button, missing-group hint when
    MISSING); `CHILDREN` section with "Restrictions ON"/"Restrictions OFF"
    labels per §4 (button labels stay Allow/Block). Error-banner pattern kept;
    all V2 grid markup gone. HTMX via CDN: HTMX 1.9.12 posts
    `hx-vals` as `application/x-www-form-urlencoded`, but the FastAPI
    Pydantic body requires JSON (verified: form-encoded → 422, JSON → 200),
    so an inline `json-body` HTMX extension (encodeParameters +
    `htmx:configRequest` Content-Type) is defined in the template and
    activated via `hx-ext="json-body"` on `#dashboard`; every button posts to
    its route with `hx-target`/`hx-select`/`hx-swap="outerHTML"` on
    `#dashboard`. Verified: render checks for all-enabled, all-disabled,
    MIXED, missing-group, and error-banner states; headless-Chrome e2e —
    clicking Gaming's Block button sent `POST /categories/gaming` with
    `Content-Type: application/json`, body `{"state":"BLOCKED"}`, and the
    dashboard swapped in place (Gaming → BLOCKED, All → MIXED).
- [x] Task 5: Tests — group-only architecture (§13)
  - Done: all three test files rewritten for the flat group model; old
    V1/V2 domain/grid/sync tests removed. `test_categories.py`: label maps
    (3 categories, 3 children incl. `finnian`), `ALL_GROUPS` composition,
    `group_state` (enabled→BLOCKED, disabled→ALLOWED, absent→MISSING),
    `all_state` (all→BLOCKED, none→ALLOWED, partial→MIXED, any absent→
    MISSING even when the rest are uniform), `build_view` row order/labels
    and per-row states. `test_pihole.py`: `get_groups` happy path + URL,
    `replace_group` PUT URL/body, URI-escaped group name, comment echoed
    verbatim; both methods keep transport/API/invalid-JSON/shape error
    tests. `test_main.py`: home builds the view (context capture) and
    renders sections/labels/"Restrictions ON"/"OFF"; missing-group hint
    text; error banners for all three error types; `GET /api/groups` JSON
    + 502; category/child BLOCKED/ALLOWED each touch exactly one group
    (comment echoed from the fetched state); unknown key → 404; invalid
    state body → 422; missing group → no PUT + named error; All sets all
    7 groups in `ALL_GROUPS` order (both directions), missing group(s) →
    no mutation, mid-fan-out failure → error banner. 64 tests pass
    (`python -m pytest tests/ -q`).
- [x] Task 6: Verification — `python -m pytest tests/ -q` + live smoke test (§14)
  - Done: all 64 tests pass (`python -m pytest tests/ -q`, 2026-08-28).
    Live smoke test against 192.168.1.115 performed manually: all three
    categories toggled BLOCKED and back to ALLOWED — displayed states
    matched Pi-hole on every toggle and the corresponding group `enabled`
    state changed as expected. All groups verified back in their original
    state (`enabled: false`) afterwards.

# V4: Weekly Internet-Control Scheduler (decisions confirmed 2026-08-29)

A very simple weekly scheduler. The user picks days, a start time and an end
time, and the Pi-hole **categories** that should be blocked during that
period. Weekday/weekend differences are just schedules with different day
sets (quick-picks in the form). No calendar UI — plain time inputs and day
checkboxes. Manual controls stay exactly as they are.

## Decisions (confirmed 2026-08-29)

1. **Window end = auto-allow.** The scheduler enforces both directions:
   a category is BLOCKED iff at least one active schedule includes it,
   ALLOWED otherwise.
2. **Overnight windows:** if `end < start`, the window runs from `start` on
   the selected day to `end` on the next day (Fri 21:00 → Sat 08:00).
   `end == start` means the full 24h day (documented in the form).
3. **Explicit pause button** (not time-limited overrides): while paused the
   scheduler never touches groups, so manual toggles persist indefinitely.
   Resuming immediately re-applies the current scheduled state (catch-up).
   While unpaused, a plain manual toggle sticks until the next boundary,
   where the schedule re-asserts.
4. **Schedule operations:** add, edit, delete (edit pre-fills the form).
5. **Scope:** the three category groups only (`streaming`, `gaming`,
   `social-media`). Children/Default are manual-only.
6. **Times are server-local** (the Pi's local time). No timezone picker.
7. **Persistence:** two JSON files in `$SCHEDULE_DIR` (default `./data`,
   `/data` in Docker): `schedules.json` (schedule definitions) and
   `scheduler-state.json` (`{paused, last_enforced}`). No database.
   `last_enforced` makes restarts and downtime safe: the tick enforces only
   categories whose scheduled state differs from the last enforced state.
   First run (no state file) initialises `last_enforced` to the current
   scheduled state WITHOUT forcing — never clobber existing Pi-hole state.
8. **Engine:** a single `asyncio` tick (interval
   `$SCHEDULER_TICK_SECONDS`, default 30, sleep before first tick) started in
   FastAPI lifespan. No APScheduler, no new dependencies (stdlib only).
9. **Failure handling:** a failed tick PUT logs/sets an error banner and
   does not update `last_enforced`, so the change retries next tick.

## Semantics reference

- `scheduled_states(schedules, dt)` → per category: BLOCKED if any schedule
  whose day-set contains `dt.weekday()` has an active window at `dt`
  (window = [day@start, day@end], or [day@start, day+1@end] when
  end < start, or [day@start, day+1@start] when end == start), else
  ALLOWED.
- A "boundary" is any window start/end. `next_change(schedules, now)` =
  first boundary after `now` (search horizon: 8 days) with the per-category
  before/after states diffed.
- Tick: if not paused, for each category where
  `scheduled_states(now)[c] != last_enforced[c]` → `GET /api/groups`,
  `replace_group(c, <fetched comment>, enabled)` for the changed ones, then
  update + save `last_enforced`. Paused → no-op.
- "Override in effect" on a category row is derived on render: actual
  Pi-hole state differs from the scheduled state. No extra bookkeeping.

## Routes (additions to the existing set)

```text
POST /schedules                  create  {name?, days, start, end, categories}
POST /schedules/{id}             edit    (same body)
POST /schedules/{id}/delete      delete  (no body)
POST /schedule/pause             pause   (no body)
POST /schedule/resume            resume  (no body; enforces catch-up)
```

All POST + JSON to match the existing HTMX `json-body` convention. Validation
failures → 422 (Pydantic): days non-empty subset of 0–6, categories non-empty
subset of the three category keys, `start`/`end` valid `HH:MM`.

## UI additions (same dark theme, HTMX, `<details>` for the form — no JS
framework, no calendar)

- SCHEDULE section (after Children):
  - Pause/Resume button with plain-language help ("While paused, your manual
    choices are kept. Resuming applies the current schedule immediately.").
  - Status block: "Now: … blocked until HH:MM" per active window and
    "Next change: HH:MM (in 1h 23m) — Gaming, Streaming → allowed" (or
    "No schedules" / paused banner).
  - One row per schedule: name-or-auto-description · days · start–end ·
    categories + Edit / Delete buttons.
  - Add/Edit form in `<details>`: optional name; Mon–Sun checkboxes +
    Weekdays / Weekends / Every day quick-picks (tiny inline JS to check
    boxes); `<input type="time">` start/end with the overnight note; category
    checkboxes.
- Content category rows gain a sub-label: "until HH:MM (scheduled)" when an
  active window applies, or "manual override — schedule says X" when actual
  differs from scheduled.

## Tasks

Tasks in order; each is marked complete in this list as it lands.

- [x] Task 1: `app/scheduler.py` — pure logic: time parsing, window
  activity (normal/overnight/all-day), `scheduled_states()`,
  `next_change()`, `describe_days()`. No I/O, no clock reads except
  arguments.
  - Done: `parse_time()` (strict `HH:MM`, ValueError on bad input),
    `is_window_active(schedule, dt)` (normal / overnight / all-day),
    `scheduled_states(schedules, dt)` (union of active schedules →
    per-category BLOCKED/ALLOWED), `next_change(schedules, now)` (first
    boundary within an 8-day horizon, per-category before/after states),
    `describe_days(days)`, `window_label(schedule)`. No I/O, no clock
    reads.
- [x] Task 2: `app/schedule_store.py` — `Schedule` model (id, name, days,
  start, end, categories) with validation; load/save `schedules.json` and
  `scheduler-state.json` in `SCHEDULE_DIR`; atomic writes (tmp + rename);
  missing/corrupt files → empty defaults (never crash on startup).
  - Done: `Schedule` dataclass + `validate()` (name string, days non-empty
    unique 0–6, start/end parseable, categories non-empty known keys;
    normalises days to sorted ints, categories to CATEGORIES order);
    `SchedulerState` (`paused`, `last_enforced`); `ScheduleStore` with
    `load_schedules/save_schedules/load_state/save_state`; atomic tmp +
    rename; missing/corrupt files → empty defaults.
- [x] Test Task 1: `tests/test_scheduler.py` — window activity (normal,
  overnight, all-day, multi-day, no overlap, just-before/just-after
  boundaries), `scheduled_states` (union across overlapping schedules),
  `next_change` (imminent boundary, overnight boundary, far boundary,
  none → no schedules), day descriptions, invalid inputs.
  - Done: all listed cases covered, including just-before/just-after
    window boundaries, overnight and `end == start` all-day windows, and
    `parse_time` rejections.
- [x] Test Task 2: `tests/test_schedule_store.py` — round-trip, validation
  rejections, corrupt/missing file defaults, atomicity (file replaced not
  appended).
  - Done: round-trips for both files, every validation rejection, corrupt
    JSON → defaults, atomicity (file content replaced, not appended).
- [x] Task 3: `app/main.py` — lifespan tick task (testable
  `scheduler_tick(client, ...)` separated from the loop); schedule CRUD +
  pause/resume routes; resume enforces catch-up through the existing
  group-update path; `GET /` context gains schedule rows, per-category
  scheduled state + "until" time, override flags, next change, paused flag;
  `SCHEDULE_DIR` / `SCHEDULER_TICK_SECONDS` env.
  - Done: `scheduler_tick(now=None)` (injectable clock and client; catches
    `PiHoleError`, sets module-level `tick_error`, leaves `last_enforced`
    unchanged on failure) driven by a lifespan loop that sleeps
    `SCHEDULER_TICK_SECONDS` (default 30) before each tick; `POST
    /schedules` (create, 422 on invalid body), `POST /schedules/{id}`
    (edit keeps id, 404 unknown), `POST /schedules/{id}/delete` (404
    unknown), `POST /schedule/pause`, `POST /schedule/resume` (re-applies
    catch-up through the shared group-update path); `schedule_view(now=None)`
    adds schedule rows, per-category scheduled state + "until" time,
    override flags (actual ≠ scheduled), next change and the paused flag to
    the `GET /` context. `SCHEDULE_DIR` (default `data`) and
    `SCHEDULER_TICK_SECONDS` (default 30) read at startup.
- [x] Task 4: `app/templates/index.html` — SCHEDULE section (pause button,
  status block, schedule rows, add/edit form in `<details>`), category-row
  sub-labels.
  - Done: SCHEDULE section after Children: Pause/Resume button with
    plain-language help; status block (per-category "Now" line, "Next
    change: … (in …)", "No schedules yet."); one row per schedule (name or
    days · days · start–end · categories + Edit/Delete); Add form in
    `<details>` with optional name, Mon–Sun checkboxes + Weekdays/Weekends/
    Every-day quick-picks (tiny `pickDays` JS), `<input type="time">`
    start/end with the overnight note, category checkboxes; Edit pre-fills
    the form (`editSchedule` JS). Paused banner replaces the status block
    while paused. Content category rows gain sub-labels: "until HH:MM
    (scheduled)" for active windows, "manual override — schedule says …"
    when actual state differs from scheduled.
- [x] Test Task 3+4: `tests/test_main.py` additions — create/edit/delete
  round-trips, 422s on bad bodies, pause/resume persistence, resume
  catch-up enforcement (mocked client), tick enforcement at a boundary,
  tick no-op while paused and while Pi-hole is down, dashboard renders
  status/next-change/override note/paused banner.
  - Done: 24 tests added; full suite 127 passing. Create: persistence +
    render, normalisation (string days, name strip), 422s (bad days, bad
    time, unknown category, missing fields). Update keeps id / replaces
    fields; unknown id 404. Delete removes; unknown id 404. Pause/resume
    persist to `scheduler-state.json`; resume re-applies a missed window
    (categories blocked, `last_enforced` updated). Tick (direct
    `asyncio.run(scheduler_tick(now=...))`): blocks at window start,
    releases at window end, no-op when in sync, skips while paused, keeps
    `last_enforced` + sets `tick_error` when Pi-hole is unreachable,
    partial failure keeps previous per-category state. Render: paused
    banner + Resume button, tick error shown while running / hidden while
    paused, now-line + next change + schedule list, override/scheduled
    sub-labels, manual override without schedules. Fixed-clock helper
    patches `app.main.datetime`; an autouse fixture isolates `SCHEDULE_DIR`
    per test.
- [x] Task 5: `compose.yaml` — `./data:/data` volume + `SCHEDULE_DIR` +
  `SCHEDULER_TICK_SECONDS` env; docs — README (scheduler feature, data
  volume), DESIGN.md (scheduling moves from out-of-scope to a design
  section: model, pause semantics, server-local time, JSON persistence).
  - Done: `compose.yaml` adds `SCHEDULE_DIR=/data`,
    `SCHEDULER_TICK_SECONDS=30` and the `./data:/data` volume. README
    gains a Scheduler section (feature, pause/resume, `./data`
    persistence) and drops the stale SQLite/APScheduler "planned" lines.
    DESIGN.md gains §16 Scheduling (model, enforcement tick, pause
    semantics, JSON persistence, server-local time); Scheduling and
    Temporary overrides removed from the §13 out-of-scope list.