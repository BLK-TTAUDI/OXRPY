# oxrpy

A Python wrapper for the [Oxford Response private server API](https://docs.oxfd.re/).

```
pip install oxrpy
```

> **2.0 targets the current API.** The old per-section endpoints (`/v1/server/players`,
> `/v1/server/vehicles`, …) stop working on **1 January 2027**. oxrpy 2.x only uses
> `GET /v1/server` and `POST /v1/server/command`, so it keeps working after that date.
> Upgrading from 1.x? See [CHANGELOG.md](CHANGELOG.md).

## Quick start

```python
import os
from oxrpy import OxfordAPI

api = OxfordAPI(os.environ["OXFD_SERVER_KEY"])

# Everything you need in ONE request (the API allows 1 of these a second per key)
data = api.get_server_data("Players", "Vehicles", "Robberies")
print(data["Server"]["Name"], "online:", data.online)
for player in data["Players"] or []:          # live sections are None while offline
    print(player["Username"], player["Team"], player["Location"])

# Or one section at a time
players = api.get_players()
staff = api.get_staff()

# Run a command and check how it went (a 200 can still be a failed command)
result = api.run_command("announce Server restart in 5 minutes")
if result["Status"] == "Failed":
    print(result["Code"], result["Message"])
```

Your server key is in **Server Management > External > API Key**, and your server needs the
**API package**. A server key gives full control of the server. Keep it on your own machine or
bot, never in website or app code people can read.

## Reading data

`get_server_data(*sections, ...)` maps directly onto `GET /v1/server`. Name any sections (case
doesn't matter). The top-level fields `Online`, `LastHeartbeat`, `NextHeartbeat`, `Cursor` and
`Server` always come back.

| Kind | Sections |
| --- | --- |
| Live | `Players`, `Tracks`, `Vehicles`, `World`, `Teams`, `Queue`, `Robberies`, `Atms`, `Incidents`, `Fires`, `Medical`, `Trees`, `TrafficLights`, `Doors`, `Radio`, `Jobs`, `Bounties`, `Economy`, `Trailers`, `Placeables`, `PlaceablesSummary` |
| Server | `Staff`, `Groups`, `Bans`, `Settings`, `Catalogue` |
| Logs | `KillLogs`, `ModCalls`, `RadioCalls`, `JoinLogs`, `Events`, `CommandLogs`, `CommandResults`, `Shots`, `Audit` |

```python
data = api.get_server_data(
    "Events", "KillLogs", "Shots",
    since=cursor,           # only entries newer than a previous response's Cursor
    limit=200,              # per log (max 500)
)

bans = api.get_bans(limit=100, offset=0)       # {"Total", "Offset", "List"}
for ban in api.iter_bans():                    # every page
    ...

audit = api.get_audit(category=["Moderation", "Staff"], user="amy_hx", limit=50)
older = api.get_audit(before=audit["Next"])

# Skip work when nothing changed
data = api.get_server_data("Players")
again = api.get_server_data("Players", if_none_match=data.etag)   # None if unchanged
```

Single-section helpers: `get_server`, `is_online`, `get_players`, `get_tracks`, `get_vehicles`,
`get_world`, `get_teams`, `get_queue`, `get_robberies`, `get_atms`, `get_incidents`,
`get_staff`, `get_groups`, `get_bans`, `iter_bans`, `get_settings`, `get_catalogue`,
`get_killlogs`, `get_modcalls`, `get_radiocalls`, `get_joinlogs`, `get_events`,
`get_commandlogs`, `get_command_results`, `get_shots`, `get_audit`.

Each helper is one request. If you need several sections, `get_server_data` with all of them is
far kinder to the rate limit.

## Following logs live

`follow()` handles `Since`/`Cursor` for you. It returns each entry once, oldest first, and
times each request for just after the server's next heartbeat.

```python
for data, new in api.follow("Events", "KillLogs", "ModCalls", sections=["Players"]):
    for event in new["Events"]:
        print(event["Type"], event)
    for kill in new["KillLogs"]:
        print(f'{kill["KillerUsername"]} downed {kill["VictimUsername"]} with {kill["Weapon"]}')
```

An entry that changes (a mod call resolved, a shot gaining its hit) comes again with a new `Seq`
and the same `Id`, so key your storage by `Id`. Save `follower.cursor` to resume after a restart:

```python
follower = api.follow("Events", cursor=saved_cursor)
data, new = follower.poll()        # one request, if you run your own loop
saved_cursor = follower.cursor
```

## Commands

```python
api.run_command(":ban m4tty_b Combat logging 7d")             # leading ':' optional
api.run_command("kick dxrkrider Exploiting", check=True)      # raises CommandFailedError if it failed

results = api.run_commands([                                  # up to 10, run in order, 1 request
    "wanted m4tty_b 2",
    "pm m4tty_b You're wanted for robbery",
    "radio Police Suspect m4tty_b last seen on Cowley Rd",
])

# Commands wait up to 8 s for a result; slower ones come back "Pending"
r = api.run_command("setting CustomVehicles [...]")
if r["Status"] == "Pending":
    r = api.wait_for_command(r["CommandId"])                  # lower-case status: succeeded / failed / no_result
```

Result `Code`s: `OK`, `TARGET_NOT_FOUND`, `INVALID_ARGS`, `FORBIDDEN`, `PACKAGE_REQUIRED`,
`RATE_LIMITED`, `OFFLINE`, `UNKNOWN_COMMAND`, `FAILED`. Every command is listed at
[docs.oxfd.re](https://docs.oxfd.re/#commands).

## App keys

If you're building an app many servers use, Oxford Roleplay can give you an app key (`oxa_…`)
with its own rate limits. Send it **as well as** the server key of the server you're acting for:

```python
api = OxfordAPI(server_key_for_that_server, app_key=os.environ["OXFD_APP_KEY"])
```

## Rate limits

By default (`rate_limit="auto"`) oxrpy paces requests to the published limits:

| Key | `GET /v1/server` with sections | Other GETs | Commands |
| --- | --- | --- | --- |
| Server key | 1/s, burst 2 | 5/s, burst 15 | 1/s |
| App key (standard tier) | 20/s, burst 40 (shared) | (shared) | 2/s, burst 5 |

On a `429` it waits `Retry-After` and retries (`max_retries`, default 3). Use
`rate_limit="none"` for a custom or unlimited app tier, or a number for the minimum seconds
between requests. The game itself also runs at most **15 commands every 10 seconds** per server.
Beyond that, commands fail with `Code: "RATE_LIMITED"`.

## Errors

```python
from oxrpy import (
    OxfordAPIError,        # base class: .status, .code, .message, .body
    AuthenticationError,   # 401/403: bad key, no API package, bad/suspended app key
    BadRequestError,       # 400: .valid_parameters lists what GET /v1/server accepts
    NotFoundError,         # 404
    RateLimitError,        # 429 after retries: .retry_after
    ServerOfflineError,    # 503: command sent while the server is offline
    CommandFailedError,    # run_command(..., check=True) and Status == "Failed": .result
)
```

Being offline isn't an error when you read data: `data.online` is `False`, live sections are
`None`, and logs, bans, staff and settings still answer.

## API status

```python
api.get_status()   # {"Status": "operational", "UptimeSeconds": ..., "LastHour": {...}, "Uptime": {...}}
```

## License

Proprietary. See [LICENSE](LICENSE).
