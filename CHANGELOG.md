# Changelog

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
