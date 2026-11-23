"""Everything the sync and async clients share: settings, request building, response handling,
and the endpoint methods themselves.

Each endpoint method builds a :class:`_Spec` and hands it to ``self._call(spec, transform)``.
The sync client runs it and returns the value; the async client returns a coroutine. That way
every endpoint is written once and works with both.
"""

from __future__ import annotations

import json
import logging
import time
import warnings
from http import HTTPStatus
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from . import __version__
from .commands import CommandHelpers
from .errors import (
    AuthenticationError,
    BadRequestError,
    CommandFailedError,
    EndpointRemovedError,
    NotFoundError,
    OxfordAPIError,
    RateLimitError,
    ServerOfflineError,
)
from .events import Handlers
from .sync import plan_group_changes, plan_staff_changes

logger = logging.getLogger("oxrpy")

BASE_URL = "https://api.oxfd.re/v1"

#: Every section ``GET /v1/server`` knows about, in the API's spelling.
SECTIONS = (
    # Live
    "Players", "Tracks", "Vehicles", "World", "Teams", "Queue", "Robberies", "Atms",
    "Incidents", "Fires", "Medical", "Trees", "TrafficLights", "Doors", "Radio", "Jobs",
    "Bounties", "Economy", "Trailers", "Placeables", "PlaceablesSummary",
    # Server
    "Staff", "Groups", "Bans", "Settings", "Catalogue",
    # Logs
    "KillLogs", "ModCalls", "RadioCalls", "JoinLogs", "Events", "CommandLogs",
    "CommandResults", "Shots", "Audit",
)

#: Sections that take ``Since``/``Limit`` and whose entries carry a ``Seq``.
LOG_SECTIONS = (
    "KillLogs", "ModCalls", "RadioCalls", "JoinLogs", "Events", "CommandLogs",
    "CommandResults", "Shots",
)

AUDIT_CATEGORIES = ("Commands", "Moderation", "Settings", "Staff", "HelpRequests", "Placeables")

MAX_BATCH = 10

_SECTION_LOOKUP = {name.lower(): name for name in SECTIONS}

USER_AGENT = f"oxrpy/{__version__} (+https://github.com/BLK-TTAUDI/OXRPY)"


class ServerData(dict):
    """The JSON from ``GET /v1/server``: a plain ``dict`` with a few extras.

    Attributes:
        etag: The response's ``ETag``. Pass it back as ``if_none_match`` to get ``None``
            when nothing has changed.
        headers: The raw response headers.
    """

    etag: Optional[str] = None
    headers: Dict[str, str] = {}

    @property
    def online(self) -> bool:
        return bool(self.get("Online"))

    @property
    def cursor(self) -> Optional[int]:
        return self.get("Cursor")


def _section_name(name: str) -> str:
    return _SECTION_LOOKUP.get(name.lower(), name)


def _retry_after(headers: Mapping[str, str], body: Any) -> Optional[float]:
    value = headers.get("Retry-After")
    if value is None and isinstance(body, dict):
        value = body.get("RetryAfter", body.get("retryAfter"))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _decode(content: bytes) -> Any:
    if not content:
        return None
    try:
        return json.loads(content)
    except ValueError:
        return None


def _check_result(result: Any) -> Any:
    if isinstance(result, dict) and str(result.get("Status", "")).lower() == "failed":
        raise CommandFailedError(result)
    return result


class _Spec:
    """One HTTP request, before it's sent."""

    __slots__ = ("method", "path", "limiter", "params", "json", "headers", "timeout", "url", "server_data")

    def __init__(
        self,
        method: str,
        path: str,
        *,
        limiter: str = "get",
        params: Optional[Dict[str, str]] = None,
        json: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        url: Optional[str] = None,
        server_data: bool = False,
    ) -> None:
        self.method = method
        self.path = path
        self.limiter = limiter
        self.params = params
        self.json = json
        self.headers = headers
        self.timeout = timeout
        self.url = url
        self.server_data = server_data


class BaseClient(CommandHelpers):
    """Shared by :class:`~oxrpy.OxfordAPI` and :class:`~oxrpy.AsyncOxfordAPI`. Don't use directly."""

    _bucket_class: Any = None  # set by subclasses

    def __init__(
        self,
        server_key: Optional[str] = None,
        *,
        app_key: Optional[str] = None,
        timeout: float = 10,
        rate_limit: Union[str, float, None] = "auto",
        max_retries: int = 3,
        base_url: str = BASE_URL,
        global_key: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> None:
        if global_key is not None:
            warnings.warn(
                "global_key is gone: the API now uses app keys sent alongside a server key. "
                "Use server_key=... and app_key=...",
                DeprecationWarning,
                stacklevel=3,
            )
            if app_key is None:
                app_key = global_key
        if server_id is not None:
            warnings.warn(
                "server_id is no longer used: the server key alone decides which server you reach.",
                DeprecationWarning,
                stacklevel=3,
            )
        if not server_key:
            raise ValueError(
                "server_key is required (Server Management > External > API Key). "
                "App keys are sent in addition to a server key, not instead of one."
            )
        if max_retries < 0:
            raise ValueError("max_retries must be 0 or more")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.has_app_key = bool(app_key)
        self.headers: Dict[str, str] = {
            "server-key": server_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if app_key:
            self.headers["Authorization"] = f"Bearer {app_key}"
        self._limiters = self._make_limiters(rate_limit)
        self._handlers = Handlers()
        self._catalogue_cache: Optional[Tuple[float, Any]] = None
        # An extra limit shared with other clients (AsyncServerPool sets it: 30/s per IP).
        self._ip_bucket: Any = None

    # ------------------------------------------------------------------ rate limits

    def _make_limiters(self, rate_limit: Union[str, float, None]) -> Dict[str, Any]:
        bucket = self._bucket_class
        none = {"data": None, "get": None, "command": None}
        if rate_limit is None or rate_limit == "none" or rate_limit is False:
            return none
        if rate_limit == "auto":
            if self.has_app_key:
                # Standard app tier: GETs 20/s burst 40 (all GETs share it), commands 2/s burst 5.
                shared = bucket(20, 40)
                return {"data": shared, "get": shared, "command": bucket(2, 5)}
            return {
                "data": bucket(1, 2),  # GET /v1/server with parameters
                "get": bucket(5, 15),  # every other GET
                "command": bucket(1, 1),  # POST /v1/server/command
            }
        if isinstance(rate_limit, (int, float)) and not isinstance(rate_limit, bool):
            if rate_limit < 0:
                raise ValueError("rate_limit must be 'auto', 'none', None or a non-negative number")
            if rate_limit == 0:
                return none
            return {k: bucket(1.0 / rate_limit, 1) for k in none}
        raise ValueError("rate_limit must be 'auto', 'none', None or a non-negative number")

    # ------------------------------------------------------------------ retries and responses

    def _url(self, spec: _Spec) -> str:
        return spec.url or f"{self.base_url}{spec.path}"

    def _network_retry_delay(self, spec: _Spec, attempt: int) -> Optional[float]:
        """Seconds to wait before retrying after a network error, or None to give up.
        Commands are never retried here: they may have run."""
        if spec.method == "GET" and attempt < self.max_retries:
            return float(min(2 ** (attempt + 1), 10))
        return None

    def _response_retry_delay(
        self, spec: _Spec, status: int, headers: Mapping[str, str], body: Any, attempt: int
    ) -> Optional[float]:
        if attempt >= self.max_retries:
            return None
        if status == 429:  # nothing was run, so commands are safe to retry too
            return _retry_after(headers, body) or float(2 ** (attempt + 1))
        if status >= 500 and status != 503 and spec.method == "GET":
            return float(min(2 ** (attempt + 1), 10))
        return None

    def _network_error(self, spec: _Spec, exc: Exception, timed_out: bool) -> OxfordAPIError:
        if timed_out:
            return OxfordAPIError(f"{spec.method} {spec.path} timed out")
        return OxfordAPIError(f"{spec.method} {spec.path} failed: {exc}")

    def _handle(self, spec: _Spec, status: int, headers: Mapping[str, str], body: Any) -> Any:
        if status == 304 and spec.server_data:
            return None
        if status >= 400:
            raise self._error(status, headers, body)
        if spec.server_data:
            data = ServerData(body or {})
            data.etag = headers.get("ETag")
            data.headers = dict(headers)
            return data
        return body

    @staticmethod
    def _error(status: int, headers: Mapping[str, str], body: Any) -> OxfordAPIError:
        try:
            reason = HTTPStatus(status).phrase
        except ValueError:
            reason = "Error"
        message = (body.get("message") if isinstance(body, dict) else None) or reason
        code = body.get("Code") if isinstance(body, dict) else None
        kwargs: Dict[str, Any] = {"status": status, "code": code, "body": body}
        if status == 400:
            return BadRequestError(message, **kwargs)
        if status in (401, 403):
            return AuthenticationError(message, **kwargs)
        if status == 404:
            return NotFoundError(message, **kwargs)
        if status == 410:
            return EndpointRemovedError(message, **kwargs)
        if status == 429:
            return RateLimitError(message, retry_after=_retry_after(headers, body), **kwargs)
        if status == 503:
            return ServerOfflineError(message, **kwargs)
        return OxfordAPIError(message, **kwargs)

    def _call(self, spec: _Spec, transform: Optional[Callable[[Any], Any]] = None) -> Any:
        raise NotImplementedError

    def _ready(self, value: Any) -> Any:
        """Return ``value`` without a request (the async client wraps it in a coroutine)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ GET /v1/server

    def _server_data_spec(
        self,
        *sections: str,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        audit_before: Optional[int] = None,
        audit_category: Union[str, Iterable[str], None] = None,
        audit_user: Union[str, int, None] = None,
        if_none_match: Optional[str] = None,
    ) -> _Spec:
        params: Dict[str, str] = {}
        for section in sections:
            params[_section_name(section)] = "true"
        if since is not None:
            params["Since"] = str(int(since))
        if limit is not None:
            params["Limit"] = str(int(limit))
        if offset is not None:
            params["Offset"] = str(int(offset))
        if audit_before is not None:
            params["AuditBefore"] = str(int(audit_before))
        if audit_category is not None:
            if not isinstance(audit_category, str):
                audit_category = ",".join(audit_category)
            params["AuditCategory"] = audit_category
        if audit_user is not None:
            params["AuditUser"] = str(audit_user)
        if not params:
            # With no parameters at all the API returns the deprecated old shape.
            # Any parameter switches to the new one; Players=false asks for nothing extra.
            params["Players"] = "false"
        headers = {"If-None-Match": if_none_match} if if_none_match else None
        return _Spec("GET", "/server", limiter="data", params=params, headers=headers, server_data=True)

    def get_server_data(
        self,
        *sections: str,
        since: Optional[int] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        audit_before: Optional[int] = None,
        audit_category: Union[str, Iterable[str], None] = None,
        audit_user: Union[str, int, None] = None,
        if_none_match: Optional[str] = None,
    ) -> Any:
        """Everything about the server in one request: ``GET /v1/server``.

        Name each section you want (case doesn't matter), e.g.
        ``api.get_server_data("Players", "Vehicles", "Events", since=cursor)``.
        The top-level fields (``Online``, ``LastHeartbeat``, ``NextHeartbeat``, ``Cursor``,
        ``Server``) always come back.

        Args:
            since: A ``Cursor`` from an earlier response: logs and shots only return newer entries.
            limit: Most entries per log/``Shots`` (default 100, max 500), ``Bans`` (max 1000)
                or ``Audit`` (max 100).
            offset: Bans to skip.
            audit_before: Audit entries numbered below this (the last ``Audit.Next``).
            audit_category: One or more of :data:`AUDIT_CATEGORIES`.
            audit_user: Only audit entries by this username or user ID.
            if_none_match: A previous response's ``etag``. Returns ``None`` if nothing changed.

        Returns:
            A :class:`ServerData` (a ``dict``), or ``None`` on ``304 Not Modified``.
        """
        return self._call(self._server_data_spec(
            *sections, since=since, limit=limit, offset=offset, audit_before=audit_before,
            audit_category=audit_category, audit_user=audit_user, if_none_match=if_none_match,
        ))

    def _section(self, name: str, *, default: Any = None, **kwargs: Any) -> Any:
        def pick(data: Any) -> Any:
            value = data.get(name) if data else None
            return default if value is None and default is not None else value

        return self._call(self._server_data_spec(name, **kwargs), pick)

    def get_server(self) -> Any:
        """The always-returned fields: ``Online``, ``LastHeartbeat``, ``NextHeartbeat``,
        ``Cursor`` and ``Server`` (name, players, join code, packages…)."""
        return self._call(self._server_data_spec())

    def is_online(self) -> Any:
        """Whether the server is running right now."""
        return self._call(self._server_data_spec(), lambda d: bool(d and d.get("Online")))

    # Live
    def get_players(self) -> Any:
        """Everyone in the server (``None`` while offline)."""
        return self._section("Players")

    def get_tracks(self) -> Any:
        """Per-second position samples since the last report (``None`` while offline)."""
        return self._section("Tracks")

    def get_vehicles(self) -> Any:
        """Every vehicle out, with emergency lights, siren, occupants… (``None`` while offline)."""
        return self._section("Vehicles")

    def get_world(self) -> Any:
        """Weather, temperature, clock, locks, speed limit, sticky message, countdown."""
        return self._section("World")

    def get_teams(self) -> Any:
        """Players, limits and access per team."""
        return self._section("Teams")

    def get_queue(self) -> Any:
        """Who's waiting to join, front first (``None`` while offline)."""
        return self._section("Queue")

    def get_robberies(self) -> Any:
        """Robbery sites: state, stage, alarm, robbers (``None`` while offline)."""
        return self._section("Robberies")

    def get_atms(self) -> Any:
        """ATMs: availability, alarm, who robbed them (``None`` while offline)."""
        return self._section("Atms")

    def get_incidents(self) -> Any:
        """The control room: open incidents, units, operators, timeline."""
        return self._section("Incidents")

    # Server
    def get_staff(self) -> Any:
        """``{ OwnerId, Staff: [...], Ranks: [...] }``."""
        return self._section("Staff")

    def get_groups(self) -> Any:
        """The server's groups and their members (``[]`` without AdvancedServer)."""
        return self._section("Groups")

    def get_bans(self, *, limit: Optional[int] = None, offset: Optional[int] = None) -> Any:
        """One page of bans: ``{ Total, Offset, List: [...] }``. See ``iter_bans``."""
        return self._section("Bans", limit=limit, offset=offset)

    def get_settings(self) -> Any:
        """Every Server Management setting, keyed by name. Webhooks read ``"(set)"``."""
        return self._section("Settings")

    def get_catalogue(self, *, max_age: float = 3600, refresh: bool = False) -> Any:
        """Game data that only changes with an update: map, places, weapons, vehicles,
        offences, teams and ranks.

        It's big and rarely changes, so the client keeps a copy for ``max_age`` seconds
        (an hour by default) and returns that instead of asking again. Pass ``refresh=True``
        to fetch a fresh copy, or ``max_age=0`` to never use the stored one.
        """
        cached = self._catalogue_cache
        if cached is not None and not refresh and max_age > 0 and time.monotonic() - cached[0] < max_age:
            return self._ready(cached[1])

        def store(data: Any) -> Any:
            value = data.get("Catalogue") if data else None
            if value is not None:
                self._catalogue_cache = (time.monotonic(), value)
            return value

        return self._call(self._server_data_spec("Catalogue"), store)

    def clear_catalogue_cache(self) -> None:
        """Forget the stored Catalogue, so the next ``get_catalogue`` asks the API."""
        self._catalogue_cache = None

    # Logs
    def get_killlogs(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """Kills (downs), newest first. Last 500 kept."""
        return self._section("KillLogs", default=[], since=since, limit=limit)

    def get_modcalls(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """Help requests, responders and resolutions, newest first. Last 300 kept."""
        return self._section("ModCalls", default=[], since=since, limit=limit)

    def get_radiocalls(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """Radio calls, newest first. Last 500 kept."""
        return self._section("RadioCalls", default=[], since=since, limit=limit)

    def get_joinlogs(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """Joins and leaves, newest first. Last 500 kept."""
        return self._section("JoinLogs", default=[], since=since, limit=limit)

    def get_events(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """About 100 kinds of game event, newest first. Last 1,000 kept."""
        return self._section("Events", default=[], since=since, limit=limit)

    def get_commandlogs(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """The newest audit log entries. Last 100 kept."""
        return self._section("CommandLogs", default=[], since=since, limit=limit)

    def get_command_results(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """Commands sent through the API and how they went. Last 200 kept."""
        return self._section("CommandResults", default=[], since=since, limit=limit)

    def get_shots(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> Any:
        """Every shot in the last 10 minutes, newest first."""
        return self._section("Shots", default=[], since=since, limit=limit)

    def get_audit(
        self,
        *,
        before: Optional[int] = None,
        category: Union[str, Iterable[str], None] = None,
        user: Union[str, int, None] = None,
        limit: Optional[int] = None,
    ) -> Any:
        """One page of the full audit log: ``{ Entries, Next, Total }``. Slower than the rest."""
        return self._section(
            "Audit", audit_before=before, audit_category=category, audit_user=user, limit=limit
        )

    # ------------------------------------------------------------------ commands

    def _command_spec(self, payload: dict) -> _Spec:
        # Commands wait up to 8 seconds server side, so always allow at least 15.
        return _Spec("POST", "/server/command", limiter="command", json=payload,
                     timeout=max(self.timeout, 15))

    def run_command(self, command: str, *, check: bool = False) -> Any:
        """Run one command (as you'd type it in game; the leading ``:`` is optional).

        Waits up to 8 seconds for the result: ``{ CommandId, Status, Code, Message }``.
        ``Status`` is ``Succeeded``, ``Failed`` or ``Pending``. A ``Failed`` command is still a
        normal return unless ``check=True``, which raises :class:`CommandFailedError`.

        Raises:
            ServerOfflineError: The server is offline (nothing was run).
            RateLimitError: Still rate limited after ``max_retries``.
        """
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        return self._call(self._command_spec({"command": command}), _check_result if check else None)

    def run_commands(self, commands: Sequence[str], *, check: bool = False) -> Any:
        """Run up to 10 commands in order, in one request. Returns one result per command."""
        commands = list(commands)
        if not commands:
            raise ValueError("commands must be a non-empty list")
        if len(commands) > MAX_BATCH:
            raise ValueError(f"Too many commands (max {MAX_BATCH} per batch)")
        if not all(isinstance(c, str) and c.strip() for c in commands):
            raise ValueError("Every command must be a non-empty string")

        def finish(results: Any) -> List[dict]:
            if isinstance(results, dict):
                results = [results]
            if check:
                for result in results:
                    _check_result(result)
            return results

        return self._call(self._command_spec({"commands": commands}), finish)

    def execute_command(self, command: str) -> Any:
        """Old name for :meth:`run_command`."""
        return self.run_command(command)

    def get_command(self, command_id: str) -> Any:
        """One command's result, for a command that was still ``Pending``.

        Keeps the API's old shape: lower-case ``Status`` (``succeeded``, ``failed``,
        ``pending``, ``no_result``). Results are kept for 7 days.
        """
        if not command_id:
            raise ValueError("command_id is required")
        return self._call(_Spec("GET", f"/server/commands/{command_id}"))

    # ------------------------------------------------------------------ staff and group sync

    def plan_staff_sync(self, desired: Mapping[Any, Optional[str]], *, remove_others: bool = False) -> Any:
        """The ``rank``/``unrank`` commands needed to make the staff match ``desired``
        (user ID -> rank name or Id, or ``None`` to remove). Reads the staff list; sends nothing.
        See :func:`oxrpy.sync.plan_staff_changes`."""

        def plan(data: Any) -> List[str]:
            staff = data.get("Staff") if data else None
            if staff is None:
                raise OxfordAPIError("Couldn't read the staff list right now; try again shortly")
            return plan_staff_changes(staff, desired, remove_others=remove_others)

        return self._call(self._server_data_spec("Staff"), plan)

    def plan_group_sync(self, group: str, members: Iterable[Any], *, remove_others: bool = True) -> Any:
        """The ``group add``/``group remove`` commands needed to make ``group`` contain exactly
        ``members`` (user IDs). Reads the groups; sends nothing."""
        members = list(members)

        def plan(data: Any) -> List[str]:
            groups = data.get("Groups") if data else None
            if groups is None:
                raise OxfordAPIError("Couldn't read the groups right now; try again shortly")
            return plan_group_changes(groups, group, members, remove_others=remove_others)

        return self._call(self._server_data_spec("Groups"), plan)

    # ------------------------------------------------------------------ misc

    def get_status(self) -> Any:
        """The API's own health (``GET /status``): status, uptime and response times.
        Needs no key; don't ask more than every 30 seconds."""
        root = self.base_url.rsplit("/v1", 1)[0]
        return self._call(_Spec("GET", "/status", url=f"{root}/status"))

    def on(self, *keys: Any) -> Any:
        """Register a handler for :meth:`run_forever`.

        Keys can be an entry ``Type`` (``"Kill"``, ``"Join"``, ``"ModCall"``, ``"SpeedCamera"``,
        any event type), a log name (``"KillLogs"``, ``"Events"``: every entry in it), ``"poll"``
        (called with the whole response after every request) or ``"error"`` (called with the
        exception when a request fails and will be retried).

        Use it as a decorator, ``@api.on("Kill")``, or directly, ``api.on("Kill", handler)``.
        """
        if keys and callable(keys[-1]):
            *names, fn = keys
            self._handlers.add(names, fn)
            return fn

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._handlers.add(keys, fn)
            return fn

        return decorator

    # Grouped managers kept from 1.x -------------------------------------------

    @property
    def servers(self) -> "Servers":
        return Servers(self)

    @property
    def logs(self) -> "Logs":
        return Logs(self)

    @property
    def commands(self) -> "Commands":
        return Commands(self)


class Servers:
    """Server and live-state endpoints (kept from 1.x)."""

    def __init__(self, api: BaseClient) -> None:
        self.api = api

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get_") or name in ("is_online", "iter_bans"):
            return getattr(self.api, name)
        raise AttributeError(name)


class Logs:
    """Log endpoints (kept from 1.x)."""

    def __init__(self, api: BaseClient) -> None:
        self.api = api

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get_") or name == "follow":
            return getattr(self.api, name)
        raise AttributeError(name)


class Commands:
    """Command endpoints (kept from 1.x)."""

    def __init__(self, api: BaseClient) -> None:
        self.api = api

    def __getattr__(self, name: str) -> Any:
        if name in ("run_command", "run_commands", "execute_command", "get_command", "wait_for_command"):
            return getattr(self.api, name)
        raise AttributeError(name)
