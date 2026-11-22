# oxrpy

A Python wrapper for the [Oxford Response private server API](https://docs.oxfd.re/). Use it to
read what's happening on your server and run commands on it from your own bot, website or tool.

```
pip install oxrpy
```

You'll need Python 3.10 or newer.

> **Upgrading from 1.x?** Oxford is switching off the old endpoints (`/v1/server/players`,
> `/v1/server/vehicles` and so on) on **1 January 2027**. Version 2 uses the new API, so it'll
> keep working after that. The data comes back in a different format, though, so check
> [CHANGELOG.md](CHANGELOG.md) before you upgrade.

## Getting started

You'll need your server's API key. The server owner can find it in **Server Management >
External > API Key**, and the server needs the **API package**.

```python
import os
from oxrpy import OxfordAPI

api = OxfordAPI(os.environ["OXFD_SERVER_KEY"])

# Grab a few sections in one request
data = api.get_server_data("Players", "Vehicles", "Robberies")
print(data["Server"]["Name"], "online:", data.online)

for player in data["Players"] or []:   # None if the server's offline
    print(player["Username"], player["Team"], player["Location"])

# Or just ask for one thing
players = api.get_players()
staff = api.get_staff()

# Run a command
result = api.run_command("announce Server restart in 5 minutes")
if result["Status"] == "Failed":
    print(result["Code"], result["Message"])
```

Keep your key private. Anyone who has it can run commands on your server, change its settings
and ban people. Keep it on your own machine or bot, and never put it in website code that
people can see.

## Reading data

`get_server_data()` lets you ask for any mix of sections in a single request. Section names
aren't case-sensitive. You'll always get `Online`, `LastHeartbeat`, `NextHeartbeat`, `Cursor`
and `Server` back too.

| Kind | Sections |
| --- | --- |
| Live | `Players`, `Tracks`, `Vehicles`, `World`, `Teams`, `Queue`, `Robberies`, `Atms`, `Incidents`, `Fires`, `Medical`, `Trees`, `TrafficLights`, `Doors`, `Radio`, `Jobs`, `Bounties`, `Economy`, `Trailers`, `Placeables`, `PlaceablesSummary` |
| Server | `Staff`, `Groups`, `Bans`, `Settings`, `Catalogue` |
| Logs | `KillLogs`, `ModCalls`, `RadioCalls`, `JoinLogs`, `Events`, `CommandLogs`, `CommandResults`, `Shots`, `Audit` |

```python
data = api.get_server_data(
    "Events", "KillLogs", "Shots",
    since=cursor,   # only entries newer than the Cursor from a previous response
    limit=200,      # max entries per log (up to 500)
)

bans = api.get_bans(limit=100, offset=0)    # one page: {"Total", "Offset", "List"}
for ban in api.iter_bans():                 # or every ban, page by page
    ...

audit = api.get_audit(category=["Moderation", "Staff"], user="amy_hx", limit=50)
older = api.get_audit(before=audit["Next"])

# Only download the data again if something's changed
data = api.get_server_data("Players")
again = api.get_server_data("Players", if_none_match=data.etag)   # None if nothing changed
```

There's also a helper for each section: `get_server`, `is_online`, `get_players`,
`get_tracks`, `get_vehicles`, `get_world`, `get_teams`, `get_queue`, `get_robberies`,
`get_atms`, `get_incidents`, `get_staff`, `get_groups`, `get_bans`, `iter_bans`,
`get_settings`, `get_catalogue`, `get_killlogs`, `get_modcalls`, `get_radiocalls`,
`get_joinlogs`, `get_events`, `get_commandlogs`, `get_command_results`, `get_shots` and
`get_audit`.

Each helper makes its own request, and you only get one of these a second with a server key.
If you need a few sections at once, ask for them all in one `get_server_data()` call.

## Following logs as they happen

`follow()` keeps checking the logs for you and only hands you entries you haven't seen yet,
oldest first. It also waits until the server's next update before asking again, so you're not
wasting requests.

```python
for data, new in api.follow("Events", "KillLogs", "ModCalls", sections=["Players"]):
    for event in new["Events"]:
        print(event["Type"], event)
    for kill in new["KillLogs"]:
        print(f'{kill["KillerUsername"]} downed {kill["VictimUsername"]} with {kill["Weapon"]}')
```

When an entry changes, for example a mod call gets resolved or a shot gets its hit recorded,
it shows up again with the same `Id`. If you're storing entries, use `Id` as the key so the new
version replaces the old one.

If your bot restarts, you can carry on from where you left off by saving `follower.cursor`:

```python
follower = api.follow("Events", cursor=saved_cursor)
data, new = follower.poll()      # one request, if you'd rather run your own loop
saved_cursor = follower.cursor
```

## Running commands

```python
api.run_command(":ban m4tty_b Combat logging 7d")          # the ':' is optional
api.run_command("kick dxrkrider Exploiting", check=True)   # raises CommandFailedError if it didn't work

results = api.run_commands([                               # up to 10 at once, run in order
    "wanted m4tty_b 2",
    "pm m4tty_b You're wanted for robbery",
    "radio Police Suspect m4tty_b last seen on Cowley Rd",
])

# Commands wait up to 8 seconds for a result. If one takes longer, it comes back as "Pending".
r = api.run_command("setting CustomVehicles [...]")
if r["Status"] == "Pending":
    r = api.wait_for_command(r["CommandId"])   # note: this one uses lower case, e.g. "succeeded"
```

A command can come back without an error and still have failed, so always check `Status`.
`Code` tells you why: `OK`, `TARGET_NOT_FOUND`, `INVALID_ARGS`, `FORBIDDEN`,
`PACKAGE_REQUIRED`, `RATE_LIMITED`, `OFFLINE`, `UNKNOWN_COMMAND` or `FAILED`. Oxford's docs
have the [full list of commands](https://docs.oxfd.re/#commands).

## App keys

If you're making something that lots of servers will use, you can ask Oxford Roleplay for an
app key (it starts with `oxa_`). It gives your app its own rate limits. You still need the
server key for whichever server you're talking to:

```python
api = OxfordAPI(server_key_for_that_server, app_key=os.environ["OXFD_APP_KEY"])
```

## Rate limits

oxrpy spaces out your requests so you stay under Oxford's limits:

| Key | `get_server_data` and the helpers | Other requests | Commands |
| --- | --- | --- | --- |
| Server key | 1 a second (bursts of 2) | 5 a second (bursts of 15) | 1 a second |
| App key (standard) | 20 a second (bursts of 40), shared | shared with the first column | 2 a second (bursts of 5) |

If you do get rate limited, it waits as long as the API asks and then tries again, up to
`max_retries` times (3 by default). If your app key has custom or unlimited limits, pass
`rate_limit="none"` to turn this off, or a number of seconds to wait between requests.

The game also has its own limit of 15 commands every 10 seconds per server. Go over it and the
extra commands fail with `RATE_LIMITED`.

## Errors

```python
from oxrpy import (
    OxfordAPIError,        # all the errors below are based on this: .status, .code, .message, .body
    AuthenticationError,   # wrong key, no API package, or a bad or suspended app key
    BadRequestError,       # a typo in a section name; .valid_parameters lists the right ones
    NotFoundError,         # e.g. a command ID that doesn't exist (results are kept for 7 days)
    RateLimitError,        # still rate limited after retrying; .retry_after says how long to wait
    ServerOfflineError,    # you sent a command while the server was offline
    CommandFailedError,    # from run_command(..., check=True); .result has the details
)
```

Reading data from an offline server doesn't raise an error. `data.online` is `False`, the live
sections are `None`, and the logs, bans, staff and settings still work.

## API status

Want to know if the API itself is up?

```python
api.get_status()   # {"Status": "operational", "UptimeSeconds": ..., "LastHour": {...}, "Uptime": {...}}
```

## License

Proprietary. See [LICENSE](LICENSE).
