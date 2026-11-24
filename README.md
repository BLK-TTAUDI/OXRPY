# oxrpy

**Documentation: [oxrpy.org](https://oxrpy.org)**

<!-- --8<-- [start:intro] -->

A Python wrapper for the [Oxford Response private server API](https://docs.oxfd.re/). Use it to
read what's happening on your server and run commands on it from your own bot, website or tool.

```
pip install oxrpy
```

If you're writing async code, like a discord.py bot, install the async extra instead:

```
pip install "oxrpy[async]"
```

You'll need Python 3.10 or newer.

> **Upgrading from 1.x?** Oxford is switching off the old endpoints (`/v1/server/players`,
> `/v1/server/vehicles` and so on) on **1 January 2027**. Version 2 uses the new API, so it'll
> keep working after that. The data comes back in a different format, though, so check
> [the changelog](https://github.com/BLK-TTAUDI/OXRPY/blob/main/CHANGELOG.md) before you upgrade.

<!-- --8<-- [end:intro] -->
<!-- --8<-- [start:getting-started] -->
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

<!-- --8<-- [end:getting-started] -->
<!-- --8<-- [start:reading-data] -->
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
for entry in api.iter_audit(category="Moderation"):    # or the whole log, page by page
    ...

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

`get_catalogue()` is the exception. The Catalogue is big and only changes when the game
updates, so oxrpy keeps a copy for an hour and hands that back instead of asking again. Pass
`refresh=True` to get a fresh one.

### Live data without extra requests

Every time oxrpy gets data from the server, it keeps the newest copy of each live section in
`api.latest`. Reading from it costs no request, which matters when you only get one a second:

```python
api.latest.players          # the newest Players oxrpy has seen (None if never, or while offline)
api.latest.vehicles
api.latest.online           # True / False
api.latest.age("Players")   # seconds since it arrived
```

The usual pattern for a bot is to keep `run_forever(sections=["Players", "Vehicles"])` going,
so `api.latest` is never more than a second or two old, and answer commands from it. Logs aren't
kept there, because each response only holds the *new* entries.

### Finding players and vehicles

These match the way Oxford's own commands do: a username or display name (any case), then a
user ID, then part of a name.

```python
api.find_player("kieran")        # one player, or None
api.players_on_team("Police")
api.staff_online()
api.find_vehicle("rj75flk")      # by registration (spaces and case don't matter) or owner
```

If a name matches more than one person, `find_player` raises `AmbiguousMatchError`, and its
`.matches` lists them, so your bot can ask which one. All four use `api.latest` when it's under
2 seconds old, and fetch otherwise (`max_age=` changes that). For lists you already have, the
same functions are in `oxrpy.lookup`.

### Autocomplete

Your editor knows the shape of everything the API sends back, so it suggests field names as
you type and flags typos before you run anything:

```python
for player in api.get_players() or []:
    player["Usernmae"]     # your editor flags this: did you mean "Username"?
```

This works in VS Code, PyCharm and anything else that understands Python type hints, with both
the normal and async clients. The data is still plain dicts, so nothing changes when your code
runs. If you want to use the types in your own code, they're in `oxrpy.types`:

```python
from oxrpy.types import Player, Vehicle

def describe(player: Player) -> str:
    return f'{player["Username"]} ({player.get("Team")})'
```

Handlers are checked too. Give the handler's argument its type, and a type checker will tell you
if it doesn't match the event:

```python
from oxrpy.types import KillLog

@api.on("Kill")
def on_kill(kill: KillLog) -> None:      # a Kill handler declared to take a JoinLog is flagged
    print(kill["Weapon"])
```

<!-- --8<-- [end:reading-data] -->
<!-- --8<-- [start:following] -->
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

The loop keeps going if the internet drops, you get rate limited or the API has a bad moment.
It waits a bit longer after each failure in a row (up to a minute) and logs a warning. It only
stops for problems that waiting won't fix, like a wrong API key, and raises those.

<!-- --8<-- [end:following] -->
<!-- --8<-- [start:events] -->
## Reacting to events

If you just want to run some code whenever something happens in game, register a handler with
`@api.on(...)` and call `run_forever()`:

```python
from oxrpy import OxfordAPI

api = OxfordAPI(key)

@api.on("Kill")
def on_kill(kill):
    print(f'{kill["KillerUsername"]} downed {kill["VictimUsername"]}')

@api.on("Join", "Leave")
def on_join_or_leave(entry):
    print(entry["Username"], entry["Type"])

@api.on("SpeedCamera")
def on_speeding(event):
    if event["SpeedMph"] > event["Limit"] + 30:
        api.pm(event["UserId"], "Slow down!")

api.run_forever()
```

You can listen for:

- Any entry type: `Kill`, `ModCall`, `RadioCall`, `Join`, `Leave`, `Command`,
  `CommandResult`, `Shot`, or any of the game events, such as `Downed`, `Jailed`,
  `RobberyStarted`, `SpeedCamera` or `IncidentOpened`. Oxford's docs list
  [every event](https://docs.oxfd.re/#events).
- A whole log, such as `"KillLogs"` or `"Events"`, to get everything in it.
- `"poll"`, which gets the whole response after every request. Pass
  `run_forever(sections=["Players"])` to have live data in it too.
- `"error"`, which gets the exception when a request fails and is about to be retried.
- `"ServerOnline"`, `"ServerOffline"` and `"ServerRestart"`, which get the whole response when
  the server comes up, goes down, or restarts. A restart means live data started over; logs
  carry on.

```python
@api.on("ServerOffline")
def went_down(data):
    print("The server is offline")

@api.on("ServerOnline")
def came_back(data):
    print(data["Server"]["Name"], "is back up")
```

oxrpy works out which logs to ask for from your handlers. Entries arrive oldest first. By
default, `run_forever()` ignores whatever was already in the logs when it started, so you don't
get a flood of old kills on startup. Pass `skip_existing=False` if you want them. If a handler
raises, the error is logged and the bot carries on. Call `api.stop()` from a handler, or from
another thread, to make `run_forever()` return.

### Carrying on after a restart

Bots restart: crashes, updates, the host rebooting. Without help, anything that happens while
your bot is down is missed. Pass `save_to` and oxrpy remembers where it got to, then picks up
exactly there next time. That includes what happened while the bot was down, as long as the
logs still hold it (the last 500 kills, 1,000 events and so on).

```python
api.run_forever(save_to="cursor.json")

# or with follow()
for data, new in api.follow("KillLogs", save_to="cursor.json"):
    ...
```

The position is saved after your handlers have run for each check, so a crash part-way through
means those entries come round again rather than being lost. To keep it somewhere other than a
file, like your bot's database, pass any object with `load()` and `save(state)` methods.

<!-- --8<-- [end:events] -->
<!-- --8<-- [start:commands] -->
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

### Command helpers

There's also a method for each command, so you don't have to build the text yourself:

```python
api.kick("dxrkrider", "Exploiting")
api.ban("m4tty_b", "Combat logging", "7d")          # or timedelta(days=7), or leave it out for permanent
api.wanted("team:Civilian", 0)
api.pm("all", "Server restart in 5 minutes")
api.set_team(81234401, "Police")
api.set_weather("thunderstorm")
api.create_incident("Police", 1, 415, 1238, "Alarm at Oxford Bank")
api.set_setting("TeamLimits", {"Police": 8, "Fire": 4})   # sent as JSON for you
```

They check your arguments before sending anything. A ban duration like `"7 days"`, a team
that doesn't exist or a wanted level of 5 raises `ValueError` straight away. Unlike
`run_command()`, the helpers raise `CommandFailedError` if the server says the command didn't
work. Pass `check=False` if you'd rather get the result back and check it yourself.

The full set:

- **Moderation:** `kick`, `ban`, `unban`, `jail`, `release`, `wanted`, `pm` and
  `resolve_modcall`.
- **Staff:** `rank`, `unrank`, `group_add` and `group_remove`.
- **Players and vehicles:** `set_team`, `respawn`, `revive`, `teleport`,
  `teleport_to_vehicle`, `set_invincible`, `give`, `despawn_vehicle`, `remove_vehicle`,
  `spawn_vehicle`, `repair` and `refuel`.
- **World and messages:** `set_time`, `lock_time`, `set_weather`, `lock_weather`,
  `announce`, `team_announce`, `alert`, `set_message`, `remove_message`, `countdown` and
  `speed_limit`.
- **Control room:** `create_incident`, `assign_incident`, `close_incident`, `radio`,
  `start_callout`, `ambulance_callout`, `list_callouts` and `stop_fires`.
- **Server:** `set_setting`, `new_join_code`, `queue_remove`, `queue_front`,
  `clear_placeables` and `shutdown`.

### Changing part of a setting

Oxford replaces a list or object setting with exactly what you send. Sending one custom vehicle
would wipe the other 149. `update_setting` reads the current value first, lets you change it,
and sends the whole thing back:

```python
api.update_setting("CustomVehicles", lambda cars: cars + [new_car])
api.update_setting("TeamLimits", lambda limits: limits.update(Police=8))   # change it in place
```

If nothing changed, nothing is sent. A misspelled name gets suggestions (setting names are
case-sensitive). Webhook settings are refused, because the API only ever shows `"(set)"` for
them, so the real URL can't be read back.

### Lots of commands at once

`run_many()` sends any number of commands in order. It batches them 10 at a time and waits
when it needs to, so you stay under the game's limit of 15 commands every 10 seconds:

```python
api.run_many([f"pm {user_id} Training starts in 5 minutes" for user_id in trainees])
```

### Keeping staff and groups in sync

If your staff ranks or groups should match something else, like Discord roles or a database,
tell oxrpy what they should be and it sends only the changes:

```python
# Roblox user ID -> rank name (or None to take them off the staff)
api.sync_staff({81234401: "Mod", 81239912: "Senior Moderator", 77001200: None})

# Make a group contain exactly these user IDs
api.sync_group("CID", [81234401, 81239912])

# See what it would do first, without sending anything
print(api.plan_staff_sync({81234401: "Admin"}))     # ['rank 81234401 admin']
```

It uses user IDs rather than usernames, because a name can change or match the wrong person.
It never touches the owner. `sync_staff` leaves alone any staff you didn't mention, unless you
pass `remove_others=True`. `sync_group` does remove anyone not in your list, unless you pass
`remove_others=False`.

<!-- --8<-- [end:commands] -->
<!-- --8<-- [start:map] -->
## Putting things on the map

Oxford publishes [a map image](https://docs.oxfd.re/map-march.png) of the whole map.
`oxrpy.map` converts API positions to pixels on it:

```python
from oxrpy.map import to_pixels, from_pixels, distance, nearest

px, py = to_pixels(player["Position"])                            # on the full-size image
px, py = to_pixels(player["Position"], width=1630, height=1260)   # on a resized copy

x, z = from_pixels(800, 600, width=1630, height=1260)    # a click on your map -> game position
api.create_incident("Police", 1, x, z, "Reported disturbance")

distance(player["Position"], vehicle["Position"])        # studs, ignoring height
nearest(player["Position"], api.get_catalogue()["Map"]["Places"])   # nearest named place
```

<!-- --8<-- [end:map] -->
<!-- --8<-- [start:async] -->
## Async (discord.py and friends)

`AsyncOxfordAPI` has all the same methods, but you `await` them, so your bot doesn't freeze
while it waits for the API. It needs `pip install "oxrpy[async]"`.

```python
import asyncio
import discord
from oxrpy import AsyncOxfordAPI

api = AsyncOxfordAPI(OXFD_SERVER_KEY)

class Bot(discord.Client):
    async def setup_hook(self):
        asyncio.create_task(api.run_forever())     # handlers run alongside the bot

bot = Bot(intents=discord.Intents.default())

@api.on("Kill")
async def on_kill(kill):                           # handlers can be async or normal functions
    channel = bot.get_channel(KILL_FEED_CHANNEL_ID)
    await channel.send(f'{kill["KillerUsername"]} downed {kill["VictimUsername"]}')

@bot.event
async def on_message(message):
    if message.content == "!players":
        players = await api.get_players() or []
        await message.channel.send(f"{len(players)} players online")

bot.run(DISCORD_TOKEN)
```

Following logs works with `async for`:

```python
async for data, new in api.follow("Events"):
    ...

async for ban in api.iter_bans():
    ...
```

Use `async with AsyncOxfordAPI(key) as api:`, or call `await api.aclose()` when you're done,
to close the connection cleanly.

<!-- --8<-- [end:async] -->
<!-- --8<-- [start:many-servers] -->
## Many servers in one app

If you're building something lots of servers use (a Discord bot, a CAD, a dashboard), each
server's owner gives your app their server key. `AsyncServerPool` follows all of them with one set
of handlers, and shares Oxford's rate limits between them fairly:

```python
from oxrpy import AsyncServerPool

pool = AsyncServerPool(app_key=os.environ.get("OXFD_APP_KEY"))   # app key optional

# When someone links their server (a /link command, say), check the key first.
info = await pool.verify(server_key)       # AuthenticationError if it's wrong
pool.add("guild-1234", server_key)         # followed straight away if the pool's running
print(f"Linked to {info['Name']}")

@pool.on("Kill")
async def on_kill(server, kill):           # the server's name comes first
    await post_to_guild(server, kill)

@pool.on("error")
async def on_error(server, exc):           # e.g. the owner regenerated their key
    await tell_guild(server, f"Lost touch with your server: {exc}")

await pool.run_forever(sections=["Players"], save_dir="positions/")
```

- **Fair turns:** when there's more to check than the limit allows, servers take turns, so none
  is left behind. Busy servers are checked more often than quiet and empty ones (which wait up to
  5 seconds, or `max_idle=`).
- **Your own requests first:** requests you make yourself, like a `/players` command's, go ahead
  of background polling, so they stay quick however many servers the pool follows.
  `pool.each()` and `pool.run_command_on_all()` wait behind them too.
- **Reuse what the pool already has:** with `sections=["Players"]` every poll brings the player
  list too, so `await pool["guild-1234"].get_players(max_age=10)` answers without a request.
  Every live helper takes `max_age`.
- **Bad keys don't spread:** a server whose key stops working is dropped, reported to your
  `error` handler and listed in `pool.failed`. The others carry on. When the owner gives you a
  new key, `await pool.update_key("guild-1234", new_key)` carries on from where it stopped.
- **Add and remove while running:** `pool.add()` and `await pool.remove()` work at any time.
- **Restarts don't miss anything:** `save_dir` keeps each server's place in its logs.
- **Custom limits just work:** with an app key, the pool follows the limits Oxford reports, so a
  higher tier needs no settings.
- **See how it's keeping up:** `pool.stats` has overall figures and each server's:

```python
stats = pool.stats
print(f"{stats.following} servers, each updated about every {stats.average_interval:.1f}s")
print(stats.per_server["guild-1234"].interval, stats.read_limit, stats.waiting)
```

### How many servers can one app follow?

Every request from one IP address counts towards Oxford's limit of 30 a second, whatever the key.
With an app key, your app's own limit (20 a second on the standard tier) is shared by every
server too. Each server needs one request per check, so the more servers, the longer each waits
for its turn:

| Servers | Each one checked about every (no app key) | (standard app key) |
| --- | --- | --- |
| up to 30 | 1 to 5 seconds, as often as it's useful | 1.5 to 5 seconds |
| 100 | 3.5 seconds | 5 seconds |
| 300 | 10 seconds | 15 seconds |
| 1,000 | 35 seconds | 50 seconds |

Nothing is missed when it's slower: each check picks up everything since the last one. It just
arrives later. `pool.stats` shows the real figures for your app.

To go further, ask Oxford Roleplay for an app key with higher limits (the pool picks them up by
itself), or run your app on more than one IP address, each with its own share of the servers.
An Unlimited app key isn't held to the per-IP limit: pass `rate_limit="none"` to turn pacing off.

<!-- --8<-- [end:many-servers] -->
<!-- --8<-- [start:app-keys] -->
## App keys

If you're making something that lots of servers will use, you can ask Oxford Roleplay for an
app key (it starts with `oxa_`). It gives your app its own rate limits. You still need the
server key for whichever server you're talking to:

```python
api = OxfordAPI(server_key_for_that_server, app_key=os.environ["OXFD_APP_KEY"])
```

<!-- --8<-- [end:app-keys] -->
<!-- --8<-- [start:rate-limits] -->
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

To see where you stand, `api.rate_limit_status` has Oxford's latest figures for each kind of
request (`"data"`, `"get"` and `"command"`): the steady rate, how many you can make right now,
and seconds until the next one is free.

To log or measure requests, register a hook. It's called after every attempt, retries
included:

```python
@api.on_request
def log_request(info):
    print(info.method, info.path, info.status, f"{info.elapsed * 1000:.0f} ms")
```

<!-- --8<-- [end:rate-limits] -->
<!-- --8<-- [start:errors] -->
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

Errors also suggest a fix where there's a likely one: `exc.hint`, which is also shown when the
error prints. For example: *403: Invalid API key (hint: Check the key in Server Management >
External > API Key. If it was regenerated, the old one stops working within a few seconds.)*

Reading data from an offline server doesn't raise an error. `data.online` is `False`, the live
sections are `None`, and the logs, bans, staff and settings still work.

<!-- --8<-- [end:errors] -->
<!-- --8<-- [start:status] -->
## API status

Want to know if the API itself is up?

```python
api.get_status()   # {"Status": "operational", "UptimeSeconds": ..., "LastHour": {...}, "Uptime": {...}}
```

<!-- --8<-- [end:status] -->
<!-- --8<-- [start:cli] -->
## From the command line

Installing oxrpy also gives you an `oxrpy` command for quick checks:

```
oxrpy status       # is the Oxford API up? (no key needed)
oxrpy server       # your server's name, player count, join code and packages
oxrpy players      # who's in your server
```

`server` and `players` read your key from the `OXFD_SERVER_KEY` environment variable. Add
`--json` to any of them to get the raw data.

<!-- --8<-- [end:cli] -->
<!-- --8<-- [start:examples] -->
## Examples

The [examples folder](https://github.com/BLK-TTAUDI/OXRPY/tree/main/examples) has scripts you
can copy and run:

- [join_leave_log.py](https://github.com/BLK-TTAUDI/OXRPY/blob/main/examples/join_leave_log.py)
  prints joins, leaves, kills and the server going up or down.
- [discord_kill_feed.py](https://github.com/BLK-TTAUDI/OXRPY/blob/main/examples/discord_kill_feed.py)
  is a Discord bot that posts kills to a channel and answers `!players`.
- [discord_server_status.py](https://github.com/BLK-TTAUDI/OXRPY/blob/main/examples/discord_server_status.py)
  is a Discord bot that posts when the server goes offline, comes back or restarts, and shows
  the player count as its status.
- [sync_staff_from_list.py](https://github.com/BLK-TTAUDI/OXRPY/blob/main/examples/sync_staff_from_list.py)
  keeps staff ranks matching a list, and shows you the changes before making them.

<!-- --8<-- [end:examples] -->
## Support

oxrpy is free to use. If it's saved you some time, you can
[buy me a coffee](https://buymeacoffee.com/blk_ttaudi) to help keep it going.

<!-- --8<-- [start:license] -->
## License

Proprietary. See the [LICENSE](https://github.com/BLK-TTAUDI/OXRPY/blob/main/LICENSE) file.
<!-- --8<-- [end:license] -->
