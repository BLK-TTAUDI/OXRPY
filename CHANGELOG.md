# Changelog

## 2.0.0

Rewritten for the current Oxford Response API (https://docs.oxfd.re). The per-section
endpoints 1.x used stop working on 1 January 2027, so **upgrade before then**.

### Breaking

- Every read now goes through `GET /v1/server?<Section>=true`. Methods return the **new data
  shapes** (PascalCase, `null` instead of placeholders), e.g. players have `Position`,
  `Location { Road, Area, Grid, Address }`, `Wanted { Level, … }` instead of `WantedLevel`,
  `Coordinates`; vehicles have `Plate`/`OwnerId`/`Els` instead of
  `Registration`/`OwnerUserId`/`ELS`.
- `get_server()` returns the top-level fields (`Online`, `LastHeartbeat`, `NextHeartbeat`,
  `Cursor`, `Server`). The server details are under `["Server"]`.
- `get_queue()` returns `[{ UserId, JoinedAt, Priority }]` instead of `{ total, users }`.
- `get_bans()` returns a page `{ Total, Offset, List }` (each ban has `ExpiresAt` instead of
  `Expiry`). Use `iter_bans()` for all of them.
- Log entries all carry `Seq`, `Id`, `Type`, `At`.
- Commands return `{ CommandId, Status, Code, Message }`. Check `Status`: a 200 can be a
  failed command.
- `server_key` is always required. `global_key` is gone. App keys (`app_key=`) are sent
  **with** a server key. Passing `global_key` warns and is treated as `app_key`.
- `server_id` is ignored (with a warning).
- Requires Python 3.9+.

### New

- `get_server_data(*sections, since=, limit=, offset=, audit_*=, if_none_match=)`: any
  combination of the API's 35 sections in one request, with ETag support.
- Helpers for the new sections: `get_tracks`, `get_world`, `get_teams`, `get_atms`,
  `get_incidents`, `get_staff`, `get_groups`, `get_settings`, `get_catalogue`, `get_events`,
  `get_shots`, `get_command_results`, `get_audit`, `is_online`, `iter_bans`.
- `follow()` / `LogFollower`: follow logs with `Since`/`Cursor`, each entry once, timed to the
  server heartbeat.
- `run_command(..., check=True)`, `run_commands([...])` (batches of up to 10),
  `get_command(id)`, `wait_for_command(id)`.
- `get_status()` for `GET /status`.
- Rate limiting matches the published limits (server key and app key tiers), and retries honour
  `Retry-After`.
- Typed exceptions: `AuthenticationError`, `BadRequestError`, `NotFoundError`,
  `EndpointRemovedError`, `CommandFailedError`, plus `.status`, `.code` and `.body` on all errors.
- Uses a persistent `requests.Session`. Works as a context manager. Ships `py.typed`.

### Kept for compatibility

- `execute_command()` (now `run_command()`), the `api.servers` / `api.logs` / `api.commands`
  managers, and `from oxrpy.oxrpy import OxfordAPI`.

## 1.3.4

Last 1.x release (per-section endpoints).
