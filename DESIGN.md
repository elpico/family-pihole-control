## 1. Purpose

A simple family-friendly web application for controlling an existing
Pi-hole installation.

The application is **not intended to replace Pi-hole**. Pi-hole remains
the DNS filtering and enforcement layer. The application provides a much
simpler UX for the common operations currently handled through the
Pi-hole UI and cron jobs:

-   Enable/disable existing restriction groups
-   Schedule restriction groups
-   Expose existing blocking rules as simple, human-friendly controls
-   Provide network-wide controls for common services such as YouTube,
    Netflix, Roblox, TikTok, etc.
-   Provide temporary overrides
-   Eventually allow secure remote management from outside the home

The initial deployment will be local to the home network. Remote access
is a later goal.

------------------------------------------------------------------------

## 2. Current Environment

### Pi-hole

Current installed versions:

-   Pi-hole Core: **v6.4.3**
-   Pi-hole Web: **v6.6**
-   Pi-hole FTL: **v6.7**

Pi-hole is connected directly to the home router.

The home LAN is believed to be `192.168.1.0/24`, with the DHCP
allocation range believed to be approximately
`192.168.1.64`--`192.168.1.253`. This should be verified before relying
on the exact network configuration.

### Existing Pi-hole groups

The current groups returned by the API are:

  ------------------------------------------------------------------------------
                  ID Name                        Enabled         Purpose /
                                                                 observed use
  ------------------ ------------------- ----------------------- ---------------
                   0 `Default`                     Yes           Pi-hole default
                                                                 group

                   1 `kids-restricted`    No at time of initial  Kids
                                               inspection        restrictions

                   2 `Orla-restricted`    No at time of initial  Orla-specific
                                               inspection        restrictions

                   3 `TV`                     No at initial      TV restrictions
                                               inspection        

                   5 `Devices`                     Yes           Existing device
                                                                 grouping
  ------------------------------------------------------------------------------

The `enabled` state changes over time, so the table above describes the
state observed during initial API inspection rather than a permanent
state.

### Existing scheduling

The current root crontab contains a summer schedule which directly
modifies the Pi-hole database:

``` cron
30 22 * * * /usr/bin/pihole-FTL sqlite3 /etc/pihole/gravity.db "UPDATE 'group' SET enabled = 1 WHERE id in (1,2);" && /usr/local/bin/pihole reloaddns

00 07 * * * /usr/bin/pihole-FTL sqlite3 /etc/pihole/gravity.db "UPDATE 'group' SET enabled = 0 WHERE id in (1,2);" && /usr/local/bin/pihole reloaddns
```

This currently means:

-   22:30: enable `kids-restricted` and `Orla-restricted`
-   07:00: disable `kids-restricted` and `Orla-restricted`

There are also commented-out school-term rules in the crontab. The
active schedule is the summer schedule.

The new application should eventually replace this cron-based
scheduling.

**Important:** the new application should use the supported Pi-hole API
rather than directly modifying `gravity.db`.

------------------------------------------------------------------------

## 3. Pi-hole API Findings

The Pi-hole v6 API is available locally under:

``` text
http://pi.hole/api/docs/
```

The local API documentation is the authoritative reference for the
installed Pi-hole version.

### Authentication

The current installation has **no Pi-hole web/API password configured**.

A request to:

``` http
GET /api/auth
```

returned:

``` json
{
  "session": {
    "valid": true,
    "totp": false,
    "sid": null,
    "validity": -1,
    "message": "no password set"
  }
}
```

This is acceptable for initial LAN-only experimentation, but a
password/authentication mechanism must be established before any remote
exposure.

### Groups

Confirmed working:

``` http
GET /api/groups
```

Example:

``` bash
curl -s http://localhost/api/groups | python3 -m json.tool
```

Individual groups can also be retrieved:

``` http
GET /api/groups/{name}
```

Example:

``` bash
curl -s http://localhost/api/groups/kids-restricted | python3 -m json.tool
```

### Group enable/disable

A write operation was successfully tested against the existing `TV`
group.

``` http
PUT /api/groups/TV
Content-Type: application/json
```

with:

``` json
{
  "name": "TV",
  "comment": null,
  "enabled": true
}
```

The request succeeded and returned:

``` json
"processed": {
  "errors": [],
  "success": [
    {
      "item": "TV"
    }
  ]
}
```

The group subsequently reported:

``` json
"enabled": true
```

The same operation can be used to disable the group by setting `enabled`
to `false`.

This is the first confirmed write operation that the application will
rely upon.

### Clients

Confirmed working:

``` http
GET /api/clients
```

The API returns client identifiers, comments/names, group assignments,
IDs and timestamps.

Examples observed:

-   `Orla Computer` → groups `0,2`
-   `Kian FireHD Ipad` → groups `0,1,3`
-   `Amazon Firestick - Lounge TV` → groups `0,1,2,3`
-   `Samsung TV` → groups `0,3`
-   `AMD Gaming PC` → groups `0,1`

This confirms that the existing Pi-hole configuration already represents
device-level restrictions using multiple group memberships.

The application should therefore **reuse these existing clients and
groups**, rather than creating a second device/group system.

### Domains

Confirmed working:

``` http
GET /api/domains?group_id=3
```

The API returned existing exact and regex deny rules, including:

-   YouTube
-   Google Video
-   Roblox
-   Roblox CDN
-   Minecraft
-   Mojang
-   Netflix
-   Prime Video
-   Instagram
-   TikTok
-   Snapchat
-   YouTube-related domains
-   BBC

The response includes:

-   domain
-   unicode representation
-   type
-   kind (`exact` or `regex`)
-   comment
-   group IDs
-   enabled state
-   domain ID
-   timestamps

Example:

``` json
{
  "domain": "^(.+[_.-])?netflix\\.[a-z]+$",
  "type": "deny",
  "kind": "regex",
  "comment": "Netflix blocker",
  "groups": [1, 2],
  "enabled": true,
  "id": 11
}
```

The existing comments are useful human-readable metadata. Examples
include:

-   `Netflix blocker`
-   `Amazon prime blocker`
-   `Instagram blocker`
-   `Tiktok blocker`
-   `Snapchat`

### Domain/group relationships

Pi-hole clearly supports domains being associated with multiple groups;
this is visible directly in the API responses through the `groups`
array.

However, during the initial API investigation, a documented v6 REST
operation for directly adding/removing an existing domain from a group
was **not established**.

Therefore:

-   Do **not** assume an undocumented domain/group mutation endpoint.
-   Do **not** make the application write directly to Pi-hole's
    database.
-   Further API investigation/testing is required before making
    domain-group membership a core write operation.

------------------------------------------------------------------------

## 4. Pi-hole Group Semantics

`Default` (group ID 0) is a special Pi-hole group.

A client which is not explicitly assigned to another group uses the
Default group. Explicitly managed clients can have Default plus
additional groups.

For example:

``` text
New/unmanaged device
    -> Default

Orla Computer
    -> Default + Orla-restricted

Kian FireHD
    -> Default + kids-restricted + TV
```

This is important for network-wide policy design.

### Desired interpretation

The application should treat Default as the potential
**baseline/network-wide policy layer**.

However, the exact mechanics for implementing network-wide blocks
through existing domain/group associations must be validated before
changing real configuration.

------------------------------------------------------------------------

## 5. Existing Restriction Model

The existing Pi-hole configuration already contains most of the actual
filtering policy.

The application should therefore be a **control plane / simplified UX**,
not a second DNS filtering system.

Existing groups:

``` text
kids-restricted
Orla-restricted
TV
```

already represent restriction profiles.

The app should expose them in simple human terms.

For example:

``` text
Kids restrictions     ON
Orla restrictions     ON
TV restrictions       OFF
```

rather than exposing Pi-hole's full technical UI.

------------------------------------------------------------------------

## 6. Network-Wide Blocks

The desired UX includes simple controls such as:

``` text
Network-wide

YouTube      BLOCKED
Netflix      ALLOWED
Roblox       BLOCKED
TikTok       BLOCKED
Instagram    BLOCKED
```

The user already has the underlying Pi-hole rules configured.

A human-friendly service may consist of multiple Pi-hole rules.

For example, YouTube currently consists of several rules, including:

-   `youtube.com`
-   `googlevideo.com`
-   `youtu.be`
-   `ytimg.com`
-   `ggpht.com`
-   `youtube-ui.l.google.com`
-   `youtube-nocookie.com`

Therefore, the application should not expose individual regexes/domains
as the primary UX.

Instead, the application should have a concept such as:

``` text
YouTube
    -> one or more underlying Pi-hole rules
```

Likewise:

``` text
Roblox
    -> roblox.com
    -> rbxcdn.com
    -> assetdelivery.roblox.com

Netflix
    -> existing Netflix regex

Prime Video
    -> existing Prime Video regex
```

The mapping between a human-friendly service and its Pi-hole rule IDs
may need to be maintained by the application.

### Important design principle

Pi-hole remains the source of truth for the actual filtering rules.

The application should not duplicate the contents of those rules.

------------------------------------------------------------------------

## 7. Desired Policy Behaviour

A key UX requirement is the relationship between network-wide and
group-specific restrictions.

### Network-wide block enabled

If the user sets:

``` text
YouTube = BLOCKED network-wide
```

the intended result is that YouTube is blocked for everyone.

Conceptually:

``` text
YouTube
    Default          BLOCKED
    Kids             BLOCKED
    Orla             BLOCKED
    TV               BLOCKED
```

### Network-wide block disabled

If the user sets:

``` text
YouTube = ALLOWED network-wide
```

that should mean:

> There is no network-wide YouTube restriction.

It should **not** automatically remove independently configured
restrictions.

For example:

``` text
YouTube
    Default          ALLOWED
    Kids             BLOCKED
    Orla             ALLOWED
    TV               ALLOWED
```

This allows individual group policies to remain independent.

### Inheritance concept

The application may eventually distinguish:

``` text
BLOCKED [inherited from network]
```

from:

``` text
BLOCKED [explicit group policy]
```

This is an application-level concept; Pi-hole does not need to know
about "inheritance".

Example:

``` text
YouTube

Whole network     BLOCKED

Kids              BLOCKED
                  inherited from network

Orla              ALLOWED

TV                BLOCKED
                  explicitly configured
```

This distinction is important when the network-wide block is removed.

------------------------------------------------------------------------

## 8. Scheduling

Scheduling should move from cron into the application.

The application should store schedules in its own database and use the
Pi-hole API to apply the desired state.

Example:

``` text
Kids + Orla restrictions

Every day
22:30 -> ON
07:00 -> OFF
```

This replaces the current:

``` cron
22:30 -> direct SQLite update
07:00 -> direct SQLite update
```

Potential future schedules:

-   Weekday/weekend schedules
-   School-term schedules
-   Summer schedules
-   Temporary overrides
-   One-off exceptions
-   Different schedules for different groups
-   Network-wide service schedules

### Temporary override

A useful UX feature:

``` text
Roblox
BLOCKED

Allow for:
[ 15 min ]
[ 30 min ]
[ 1 hour ]
[ Until bedtime ]
```

The application records the override and restores the scheduled state
automatically.

------------------------------------------------------------------------

## 9. Proposed UX

The application should deliberately be much simpler than Pi-hole's
native interface.

### Dashboard

``` text
FAMILY CONTROL

NETWORK

YouTube       BLOCKED
Netflix       ALLOWED
Roblox        BLOCKED
TikTok        BLOCKED


RESTRICTIONS

Kids          ON
Orla          ON
TV            OFF


SCHEDULE

Kids + Orla
22:30 -> 07:00
```

### Network controls

Show common services as simple toggles:

``` text
YouTube
Netflix
Roblox
TikTok
Instagram
Prime Video
Minecraft
Snapchat
```

### Restriction profiles

Expose existing Pi-hole groups:

``` text
Kids restrictions
Orla restrictions
TV restrictions
```

### Devices

Use existing Pi-hole client names/comments.

The user sees:

``` text
Orla Computer
Kian FireHD
Lounge TV
AMD Gaming PC
```

rather than MAC addresses.

------------------------------------------------------------------------

## 10. Proposed Technical Stack

### Backend

**Python + FastAPI**

Reasons:

-   Fits existing Python experience
-   Natural API-oriented architecture
-   Automatic OpenAPI documentation
-   Clean request/response validation
-   Easy separation of Pi-hole client, scheduler and application logic

### Frontend

Initial preference:

**Jinja2 + HTMX**

This avoids the complexity of a full SPA while allowing a responsive,
modern web interface.

React/TypeScript can be introduced later if the application grows
substantially.

### Database

**SQLite** initially.

The database should contain application state such as:

-   Friendly service definitions
-   Service → Pi-hole domain IDs
-   Schedules
-   Temporary overrides
-   Application metadata

It should **not** duplicate Pi-hole's complete filtering database.

### Scheduler

**APScheduler** or an equivalent application scheduler.

The scheduler should be responsible for application schedules rather
than system cron.

### Deployment

**Docker Compose** on the Raspberry Pi 5.

Docker is the preferred deployment mechanism because the Pi 5 has ample resources for this lightweight application and containerisation gives us a clean, reproducible deployment from the GitHub repository.

Target structure:

```text
Raspberry Pi 5

├── Pi-hole
│
└── Family Control
    └── Docker container
        ├── FastAPI
        ├── Jinja2
        ├── HTMX
        ├── SQLite
        └── Scheduler
```

Pi-hole and Family Control should remain separate services/containers.

The Family Control container should be ARM64-compatible and configured with:

- Automatic restart
- Persistent SQLite storage via a Docker volume/bind mount
- Environment-based configuration/secrets
- A health check
- Straightforward container logging
- A single exposed HTTP port for LAN access

There is no requirement for additional containers such as PostgreSQL, Redis, Node.js, nginx or a separate frontend service.

A Python virtual environment/systemd deployment is a possible alternative, but is not the preferred deployment model.

Initial deployment can simply build the container on the Raspberry Pi from the GitHub repository. A later iteration can add GitHub Actions/CI and automated image publishing if useful.

------------------------------------------------------------------------

## 11. Repository / Deployment

The project will be maintained in a GitHub repository and deployed to
the Raspberry Pi.

Suggested repository:

``` text
family-pihole-control/
```

Suggested structure:

``` text
family-pihole-control/
├── app/
│   ├── main.py
│   ├── pihole.py
│   ├── models.py
│   ├── scheduler.py
│   ├── routes/
│   └── templates/
├── tests/
├── docker/
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── DESIGN.md
├── README.md
└── .gitignore
```

The Pi-hole API connection should be isolated behind a `PiHoleClient`
abstraction.

Example conceptual interface:

``` python
class PiHoleClient:
    def get_groups(self):
        ...

    def get_group(self, name):
        ...

    def set_group_enabled(self, name, enabled):
        ...

    def get_clients(self):
        ...

    def get_domains(self, group_id=None):
        ...
```

This prevents Pi-hole-specific HTTP details from leaking throughout the
application.

------------------------------------------------------------------------

## 12. Security

Current Pi-hole API authentication is not configured because the
installation currently has no Pi-hole password.

That is acceptable for initial LAN-only development/testing.

Before remote access is introduced:

-   Configure Pi-hole authentication.
-   Store credentials outside source control.
-   Use environment variables/secrets.
-   Do not expose Pi-hole's API directly to the Internet.
-   Add authentication to Family Control itself.
-   Prefer a private network/VPN solution such as Tailscale for remote
    access.

Desired eventual topology:

``` text
Phone outside home
       |
    Tailscale
       |
       v
Raspberry Pi
       |
       +-- Family Control
       |
       +-- Pi-hole
       |
       +-- Home LAN
```

No direct Internet exposure of the Pi-hole API should be required.

------------------------------------------------------------------------

## 13. Initial MVP

The first implementation should deliberately be small.

### Phase 1 --- Read-only discovery

-   Connect to Pi-hole API
-   Display groups
-   Display clients
-   Display group assignments
-   Display domain rules
-   Identify existing service/block definitions

### Phase 2 --- Group control

-   Toggle `kids-restricted`
-   Toggle `Orla-restricted`
-   Toggle `TV`
-   Confirm state through API
-   Replace existing cron functionality

### Phase 3 --- Scheduling

-   Store schedules in SQLite
-   Schedule group enable/disable
-   Replace current cron jobs
-   Add temporary overrides

### Phase 4 --- Network-wide services

-   Define human-friendly services
-   Map services to existing Pi-hole domain IDs
-   Determine the safest supported API mechanism for service/group
    membership
-   Implement network-wide toggles
-   Preserve independent group restrictions

### Phase 5 --- Devices

-   Friendly device list
-   Device/group management
-   Better handling of newly discovered devices
-   Potential device ownership/person model

### Phase 6 --- Remote access

-   Authentication
-   Tailscale
-   HTTPS/private access
-   Remote management

------------------------------------------------------------------------

## 14. Important Open Questions

These should be resolved before implementing destructive or
configuration-changing features.

### Domain/group API

We have not yet established a documented v6 REST operation for
adding/removing an existing domain from a group.

Do not assume such an endpoint exists.

### Network-wide service implementation

We need to decide whether network-wide service blocks should be
represented using:

1.  Default group membership
2.  A dedicated network-wide group
3.  Existing groups
4.  Another Pi-hole-supported mechanism

The desired UX is clear; the exact Pi-hole implementation should be
validated first.

### Group evaluation

The interaction between:

-   Default
-   custom groups
-   enabled/disabled groups
-   multi-group clients
-   multi-group domains

should be tested against the real installation before implementing
inheritance assumptions.

### IPv6

The current design discussion has focused on the IPv4 LAN
(`192.168.1.0/24`).

IPv6 behaviour should be investigated before claiming that a
network-wide DNS policy covers every device.

------------------------------------------------------------------------

## 15. Design Principles

1.  **Pi-hole remains the enforcement engine.**
2.  **The application is a simplified control plane.**
3.  **Reuse existing Pi-hole groups and clients wherever possible.**
4.  **Do not duplicate Pi-hole's domain/rule database.**
5.  **Do not modify `gravity.db` directly from the application.**
6.  **Use the supported Pi-hole API for writes.**
7.  **Keep human-friendly concepts separate from Pi-hole implementation
    details.**
8.  **Network-wide and group-specific restrictions should be
    independently understandable.**
9.  **Schedules belong to the application, not system cron.**
10. **Remote access should use a private network/VPN rather than
    exposing Pi-hole publicly.**
11. **Start small and validate each Pi-hole API operation against the
    real installation before building abstractions around it.**

------------------------------------------------------------------------

## 16. Current Status

Confirmed against the real Pi-hole installation:

-   Pi-hole v6.4.3 Core / Web 6.6 / FTL 6.7
-   API available locally
-   Authentication endpoint working
-   Groups can be read
-   Clients can be read
-   Domains can be read
-   Group enable/disable can be performed through `PUT`
-   Existing group/client/domain configuration has been inspected
-   Existing cron-based restriction scheduling has been identified

The next implementation milestone is to create the GitHub repository and
build a minimal FastAPI application that can **read the existing Pi-hole
configuration and safely toggle an existing group**.
