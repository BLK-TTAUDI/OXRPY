# Changelog

## 2.2.0

Nothing in this release should break code written for 2.0 or 2.1.

### New

- **Autocomplete.** Editors now know the shape of everything the API returns, so they suggest
  field names (`Username`, `SpeedMph`, `Wanted`…) and flag typos before you run your code. The
  types are in `oxrpy.types` if you want them in your own code. At runtime it's all still
  plain dicts.
- **Server online, offline and restart events.** Handlers can listen for `"ServerOnline"`,
  `"ServerOffline"` and `"ServerRestart"`.
- **Staff and group sync.** `sync_staff({user_id: rank})` and `sync_group(name, user_ids)`
  send only the changes needed. `plan_staff_sync` and `plan_group_sync` show those changes
  without sending anything.
- **`run_many()`** sends any number of commands, batching them and waiting when needed to stay
  under the game's 15 commands every 10 seconds.
- **Map helpers.** `oxrpy.map` converts positions to pixels on Oxford's map image and back,
  and works out distances and the nearest place.
- **Catalogue caching.** `get_catalogue()` keeps a copy for an hour. Pass `refresh=True` to
  fetch a new one.
- **Command line.** `oxrpy status`, `oxrpy server` and `oxrpy players`.
- **Examples.** Ready-to-run scripts in
  [examples/](https://github.com/BLK-TTAUDI/OXRPY/tree/main/examples), including Discord bots
  for a kill feed and server status.

### Fixed

- Return types are back in your editor. In 2.1.0, every method showed up as returning `Any`.
- The changelog and license links on the PyPI page work now. They used to point at files
  PyPI doesn't have.
- The source download on PyPI no longer includes the tests.

## 2.1.0

Nothing in this release should break code written for 2.0.

### New

- **Async client.** `AsyncOxfordAPI` has every method `OxfordAPI` has, but you `await`
  them, so discord.py bots and other async code don't freeze while waiting for the API. Install
  it with `pip install "oxrpy[async]"`, which adds `httpx`.
- **Event handlers.** Register functions with `@api.on("Kill")`, `@api.on("Join", "Leave")`,
  `@api.on("SpeedCamera")` and so on, then call `api.run_forever()`. oxrpy works out which
  logs to ask for. Entries arrive oldest first, and old entries are skipped on startup. If a
  handler raises, the error is logged and the bot keeps going. There are also `"poll"` and
  `"error"` handlers, and `api.stop()`.
- **Command helpers.** There's a method for every command, such as `api.kick(...)`,
  `api.ban(user, reason, "7d")`, `api.set_team(...)`, `api.create_incident(...)` and
  `api.set_setting(...)`. They check arguments before sending, so typos fail straight away,
  and they raise `CommandFailedError` if the command didn't work (pass `check=False` to turn
  that off). `format_duration()` turns a `timedelta` or seconds into a ban duration.

### Changed

- `follow()` no longer stops when a request fails. It waits and tries again, waiting longer
  after each failure in a row (up to a minute), and only stops for errors that waiting won't
  fix, like a wrong key. Use `follower.iter(retry=False)` for the old behaviour.

## 2.0.1

- Rewrote the README to be easier to read. No code changes.

## 2.0.0

This version is a full rewrite for Oxford's new API (https://docs.oxfd.re). The endpoints
1.x used are being switched off on 1 January 2027, so you'll need to upgrade before then.

### What might break your code

- All the data now comes from the new API, so it's in the new format. Field names are
  PascalCase, and anything missing is `None` instead of a placeholder like `"None"` or `0`.
  For example:
  - Players have `Position` and `Location { Road, Area, Grid, Address }`, where they used to
    have `Coordinates`.
  - `WantedLevel` is now `Wanted { Level, ... }`.
  - Vehicles use `Plate`, `OwnerId` and `Els` in place of `Registration`, `OwnerUserId` and
    `ELS`.
- `get_server()` now returns `Online`, `LastHeartbeat`, `NextHeartbeat`, `Cursor` and
  `Server`. The server's details are under `["Server"]`.
- `get_queue()` returns a list like `[{ UserId, JoinedAt, Priority }]` instead of
  `{ total, users }`.
- `get_bans()` returns one page at a time as `{ Total, Offset, List }`, and each ban has
  `ExpiresAt` instead of `Expiry`. Use `iter_bans()` if you want all of them.
- Every log entry now has `Seq`, `Id`, `Type` and `At`.
- Commands return `{ CommandId, Status, Code, Message }`. A command can fail without raising
  an error, so check `Status`.
- You always need a `server_key` now. `global_key` has gone. If you've got an app key, pass it
  as `app_key=` along with the server key. If you still pass `global_key`, you'll get a warning
  and it'll be used as the app key.
- `server_id` isn't needed any more. If you pass it, you'll get a warning and it's ignored.
- You need Python 3.10 or newer.

### What's new

- `get_server_data()` gets any mix of the API's 35 sections in one request. You can also pass
  an ETag so it only downloads the data again when something's changed.
- New helpers for the new sections: `get_tracks`, `get_world`, `get_teams`, `get_atms`,
  `get_incidents`, `get_staff`, `get_groups`, `get_settings`, `get_catalogue`, `get_events`,
  `get_shots`, `get_command_results`, `get_audit`, `is_online` and `iter_bans`.
- `follow()` watches the logs for you and only gives you entries you haven't seen yet.
- `run_commands()` sends up to 10 commands at once. `run_command(..., check=True)` raises an
  error if the command didn't work. `get_command()` and `wait_for_command()` let you check on
  slow commands.
- `get_status()` tells you whether the API itself is up.
- Rate limiting now matches Oxford's published limits for server keys and app keys. When you
  get rate limited, it waits as long as the API asks before trying again.
- Each kind of error has its own exception: `AuthenticationError`, `BadRequestError`,
  `NotFoundError`, `EndpointRemovedError` and `CommandFailedError`. They all have `.status`,
  `.code` and `.body`.
- Requests reuse one connection, you can use the client in a `with` block, and the package
  includes type hints.

### Still works from 1.x

- `execute_command()` (it's called `run_command()` now), `api.servers`, `api.logs`,
  `api.commands`, and `from oxrpy.oxrpy import OxfordAPI`.

## 1.3.4

The last 1.x release, which used the old endpoints.
