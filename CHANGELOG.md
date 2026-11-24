# Changelog

## 2.6.0

Nothing in this release should break existing code.

- **Outages handled together:** when Oxford's API itself goes down, `AsyncServerPool` notices
  (most servers failing at once), holds every server's polling back, and checks with one request
  at a time (after 2s, then 4, 8... up to a minute). The first answer lets everyone carry on
  straight away. `pool.stats.api_down` shows when it's waiting. Before, every server retried on
  its own, and could take up to a minute after the API came back to notice.
- **Lighter start:** the first poll of `run_forever` (and the pool) only asks for the newest
  entry of each log when what's there would be skipped anyway. Much less to download when an
  app starts up with hundreds of servers. A `"poll"` handler sees just that one entry per log on
  the first poll.
- **Background polls report failures straight away**, rather than retrying inside the request
  first; the poll loop does the retrying.
- **Faster bookkeeping** for large pools: request counts and the JavaScript version's queues no
  longer slow down with thousands of servers.

## 2.5.0

Nothing in this release should break existing code.

### For apps that follow many servers

- **Fair turns:** `AsyncServerPool` shares the rate limit between servers in turn, instead of
  every server racing for each free slot. Nobody's left behind, however many servers there are.
- **Your own requests first:** requests you make yourself (a Discord command's lookup) go ahead
  of background polling, with the async client too. `pool.each()` and
  `pool.run_command_on_all()` wait behind them.
- **`pool.stats`:** how the pool is keeping up, overall and per server (`PoolStats`,
  `ServerStats`), including how often each server is really being checked.
- **`pool.verify(key)`:** checks a server key (for a `/link` command) and returns the server's
  details, without adding it.
- **`pool.update_key(name, key)`:** swaps in a new key and carries on where it stopped.
- **Limits that follow Oxford:** with an app key, the limits Oxford reports are used, so custom
  tiers work without settings.
- **`max_age=` on every live helper** (`get_players`, `get_vehicles`, `get_staff`...): answers
  from `api.latest` without a request when it's that fresh.
- **Quick shutdown:** stopping a pool stops every server at once, and polls still waiting for
  their turn are dropped instead of being sent first.

## 2.4.0

Nothing in this release should break existing code.

### New

- **Live data without extra requests.** `api.latest` keeps the newest copy of each live section
  the client has received (`.players`, `.vehicles`, `.online`, `.world` and the rest), with
  `.age(section)` to see how fresh it is. Bots can answer commands from it instead of making a
  request each time.
- **Finding players and vehicles** the way Oxford's commands do: `find_player("kieran")`,
  `players_on_team("Police")`, `staff_online()`, `find_vehicle("rj75flk")`. They use
  `api.latest` when it's fresh. A name matching several players raises `AmbiguousMatchError`,
  with the matches. The same functions are in `oxrpy.lookup`.
- **`update_setting(name, change)`** reads a setting, applies your change and sends the whole
  value back, so adding one custom vehicle doesn't wipe the rest. It skips sending if nothing
  changed, suggests names for typos, and refuses webhook settings, which can't be read back.
- **`iter_audit()`** pages through the whole audit log.
- **`rate_limit_status`** shows Oxford's latest rate limit figures, and **`on_request(hook)`**
  calls your function after every request, for logging and metrics.
- **Smarter polling for many servers.** `AsyncServerPool` checks quiet and empty servers less
  often (up to every 5 seconds) and busy ones on every update, so one app can follow far more
  servers. `run_forever(adaptive=True)` does the same for a single client.
- **Typed handlers.** Type checkers now know what each `on(...)` handler receives (a `KillLog`
  for `"Kill"`, a `JoinLog` for `"Join"`, the response for `"poll"`, and so on), so a mismatched
  handler is flagged.
- **Errors suggest fixes.** Common errors have a `hint`, which is also shown when they print:
  where to find your key, which package a command needs, and "did you mean" for a misspelled
  section.

## 2.3.1

A security release. Upgrading is recommended; nothing should break.

### Security

- **Redirects are never followed.** If anything answered with a redirect to another site, the
  `server-key` header used to go with it, because `requests` only strips the standard
  `Authorization` header. oxrpy now refuses redirects and raises an error instead. The async
  client does the same, even if you pass it an httpx client set to follow redirects.
- **Your own session is left alone.** Passing `session=` used to add your server key to that
  session's default headers, so it went out with every other request you made with it. The key
  is now sent with oxrpy's own requests only.
- **HTTPS only.** `base_url` must be `https://` (plain `http://` is allowed for `localhost`,
  for testing), so the key is never sent unencrypted.
- **Needs requests 2.32.4 or newer**, which fixes CVE-2024-47081 (a credential leak), and
  httpx 0.27 or newer for the async extra.
- A `Retry-After` from the API can't make oxrpy wait more than a minute.
- Command IDs are escaped in `get_command()`, so an ID taken from user input can't reach a
  different API path.
- `AsyncServerPool(save_dir=...)` gives every server its own file, even when two names look
  alike once made safe for a file name (like `"a/b"` and `"a_b"`).

### Other

- The docs are now at **https://oxrpy.org**, the package's "Documentation" link on PyPI.
- The docs website has moved to its own repository, so this one only holds the wrapper. The
  site is still built from this README, the changelog and the code's docstrings, so they stay
  the place to edit the docs' content.
- GitHub Actions are pinned to exact versions, jobs get read-only access by default, and
  Dependabot proposes updates.

## 2.3.0

Nothing in this release should break existing code.

### New

- **Carry on after a restart.** `run_forever(save_to="cursor.json")` and
  `follow(..., save_to=...)` remember where they got to. After a restart, your bot picks up
  exactly there, including anything that happened while it was down, as long as the logs still
  hold it. The position is saved after your handlers run, so a crash never loses entries. To
  keep it in your own database, pass any object with `load()` and `save(state)`.
- **Many servers in one app.** `AsyncServerPool` runs one set of handlers across lots of
  servers. Handlers get the server's name first.
  - With an app key, every server's requests are paced together within your app's limits.
  - A server whose key stops working is dropped and reported, and the rest carry on.
  - You can add and remove servers while it runs.
  - `each()` and `run_command_on_all()` do something on every server at once.
- **Docs site.** Full guides and a reference for every method, built from this README, the
  changelog and the docstrings.

### Fixed

- Hovering over a method in your editor shows its description again, as well as its types.
  Since 2.2.0, some editors showed only the types.
- `OxfordAPI(...)` and `AsyncOxfordAPI(...)` list their arguments properly, so editors
  autocomplete them.

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
