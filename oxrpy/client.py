"""The Oxford Response private server API client."""

from __future__ import annotations

import logging
import time
import warnings
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import requests

from . import __version__
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
from .ratelimit import TokenBucket

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


def _retry_after(response: requests.Response, body: Any) -> Optional[float]:
    value = response.headers.get("Retry-After")
    if value is None and isinstance(body, dict):
        value = body.get("RetryAfter", body.get("retryAfter"))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class OxfordAPI:
    """Client for the Oxford Response private server API (https://docs.oxfd.re).

    Args:
        server_key: Your server's API key (Server Management > External > API Key).
        app_key: Optional app key (``oxa_…``) from Oxford Roleplay, for apps used by many
            servers. Sent as ``Authorization: Bearer <app_key>`` alongside the server key.
        timeout: Seconds to wait for a response. Commands wait up to 8 seconds server side,
            so command requests always get at least 15.
        rate_limit: ``"auto"`` (default) paces requests to stay inside the API's published
            limits; ``"none"``/``None`` turns client-side pacing off; a number is the minimum
            seconds between requests of each kind.
        max_retries: How many times to retry after a 429 (waiting ``Retry-After``) or a
            network error / 500 on a read.
        base_url: Override the API base URL (for testing).
        session: Use your own ``requests.Session``.
    """

    def __init__(
        self,
        server_key: Optional[str] = None,
        *,
        app_key: Optional[str] = None,
        timeout: float = 10,
        rate_limit: Union[str, float, None] = "auto",
        max_retries: int = 3,
        base_url: str = BASE_URL,
        session: Optional[requests.Session] = None,
        global_key: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> None:
        if global_key is not None:
            warnings.warn(
                "global_key is gone: the API now uses app keys sent alongside a server key. "
                "Use OxfordAPI(server_key=..., app_key=...).",
                DeprecationWarning,
                stacklevel=2,
            )
            if app_key is None:
                app_key = global_key
        if server_id is not None:
            warnings.warn(
                "server_id is no longer used: the server key alone decides which server you reach.",
                DeprecationWarning,
                stacklevel=2,
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

        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "server-key": server_key,
                "Accept": "application/json",
                "User-Agent": f"oxrpy/{__version__} (+https://github.com/BLK-TTAUDI/OXRPY)",
            }
        )
        if app_key:
            self.session.headers["Authorization"] = f"Bearer {app_key}"

        self._limiters = self._make_limiters(rate_limit)

    # ------------------------------------------------------------------ plumbing

    def _make_limiters(self, rate_limit: Union[str, float, None]) -> Dict[str, Optional[TokenBucket]]:
        if rate_limit is None or rate_limit == "none" or rate_limit is False:
            return {"data": None, "get": None, "command": None}
        if rate_limit == "auto":
            if self.has_app_key:
                # Standard app tier: GETs 20/s burst 40 (all GETs share it), commands 2/s burst 5.
                shared = TokenBucket(20, 40)
                return {"data": shared, "get": shared, "command": TokenBucket(2, 5)}
            return {
                "data": TokenBucket(1, 2),  # GET /v1/server with parameters
                "get": TokenBucket(5, 15),  # every other GET
                "command": TokenBucket(1, 1),  # POST /v1/server/command
            }
        if isinstance(rate_limit, (int, float)) and not isinstance(rate_limit, bool):
            if rate_limit < 0:
                raise ValueError("rate_limit must be 'auto', 'none', None or a non-negative number")
            if rate_limit == 0:
                return {"data": None, "get": None, "command": None}
            rate = 1.0 / rate_limit
            return {k: TokenBucket(rate, 1) for k in ("data", "get", "command")}
        raise ValueError("rate_limit must be 'auto', 'none', None or a non-negative number")

    def _request(
        self,
        method: str,
        path: str,
        *,
        limiter: str,
        params: Optional[Dict[str, str]] = None,
        json: Any = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        url: Optional[str] = None,
    ) -> requests.Response:
        url = url or f"{self.base_url}{path}"
        bucket = self._limiters.get(limiter)
        attempt = 0
        while True:
            if bucket is not None and not bucket.acquire(timeout=60):
                raise RateLimitError(f"Timed out waiting for a rate limit slot for {path}")
            try:
                response = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=timeout or self.timeout,
                )
            except requests.Timeout as exc:
                # A command may still have run, so only retry reads.
                if method == "GET" and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 10))
                    continue
                raise OxfordAPIError(f"{method} {path} timed out") from exc
            except requests.RequestException as exc:
                if method == "GET" and attempt < self.max_retries:
                    attempt += 1
                    time.sleep(min(2 ** attempt, 10))
                    continue
                raise OxfordAPIError(f"{method} {path} failed: {exc}") from exc

            if response.status_code == 429 and attempt < self.max_retries:
                attempt += 1
                wait = _retry_after(response, self._json(response)) or 2 ** attempt
                if bucket is not None:
                    bucket.drain()
                logger.warning("Rate limited on %s %s, retrying in %.1fs", method, path, wait)
                time.sleep(wait)
                continue
            if response.status_code >= 500 and response.status_code != 503 and method == "GET" \
                    and attempt < self.max_retries:
                attempt += 1
                time.sleep(min(2 ** attempt, 10))
                continue

            logger.debug("%s %s -> %s", method, path, response.status_code)
            return response

    @staticmethod
    def _json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _raise_for_error(self, response: requests.Response, body: Any) -> None:
        status = response.status_code
        if status < 400:
            return
        message = (body.get("message") if isinstance(body, dict) else None) or response.reason or "Error"
        code = body.get("Code") if isinstance(body, dict) else None
        kwargs = {"status": status, "code": code, "body": body}
        if status == 400:
            raise BadRequestError(message, **kwargs)
        if status in (401, 403):
            raise AuthenticationError(message, **kwargs)
        if status == 404:
            raise NotFoundError(message, **kwargs)
        if status == 410:
            raise EndpointRemovedError(message, **kwargs)
        if status == 429:
            raise RateLimitError(message, retry_after=_retry_after(response, body), **kwargs)
        if status == 503:
            raise ServerOfflineError(message, **kwargs)
        raise OxfordAPIError(message, **kwargs)

    def _get_json(self, path: str, *, limiter: str = "get", **kwargs: Any) -> Any:
        response = self._request("GET", path, limiter=limiter, **kwargs)
        body = self._json(response)
        self._raise_for_error(response, body)
        return body

    # ------------------------------------------------------------------ GET /v1/server

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
    ) -> Optional[ServerData]:
        """Everything about the server in one request: ``GET /v1/server``.

        Name each section you want (case doesn't matter), e.g.
        ``api.get_server_data("Players", "Vehicles", "Events", since=cursor)``.
        The top-level fields (``Online``, ``LastHeartbeat``, ``NextHeartbeat``, ``Cursor``,
        ``Server``) always come back.

        Args:
            *sections: Section names; see :data:`SECTIONS`.
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
        response = self._request("GET", "/server", limiter="data", params=params, headers=headers)
        if response.status_code == 304:
            return None
        body = self._json(response)
        self._raise_for_error(response, body)
        data = ServerData(body or {})
        data.etag = response.headers.get("ETag")
        data.headers = dict(response.headers)
        return data

    def _section(self, name: str, **kwargs: Any) -> Any:
        data = self.get_server_data(name, **kwargs)
        assert data is not None
        return data.get(name)

    # Top level --------------------------------------------------------------

    def get_server(self) -> ServerData:
        """The always-returned fields: ``Online``, ``LastHeartbeat``, ``NextHeartbeat``,
        ``Cursor`` and ``Server`` (name, players, join code, packages…)."""
        data = self.get_server_data()
        assert data is not None
        return data

    def is_online(self) -> bool:
        """Whether the server is running right now."""
        return self.get_server().online

    # Live sections ------------------------------------------------------------

    def get_players(self) -> Optional[List[dict]]:
        """Everyone in the server (``None`` while offline)."""
        return self._section("Players")

    def get_tracks(self) -> Optional[dict]:
        """Per-second position samples since the last report (``None`` while offline)."""
        return self._section("Tracks")

    def get_vehicles(self) -> Optional[List[dict]]:
        """Every vehicle out, with emergency lights, siren, occupants… (``None`` while offline)."""
        return self._section("Vehicles")

    def get_world(self) -> Optional[dict]:
        """Weather, temperature, clock, locks, speed limit, sticky message, countdown."""
        return self._section("World")

    def get_teams(self) -> Optional[dict]:
        """Players, limits and access per team."""
        return self._section("Teams")

    def get_queue(self) -> Optional[List[dict]]:
        """Who's waiting to join, front first (``None`` while offline)."""
        return self._section("Queue")

    def get_robberies(self) -> Optional[List[dict]]:
        """Robbery sites: state, stage, alarm, robbers (``None`` while offline)."""
        return self._section("Robberies")

    def get_atms(self) -> Optional[List[dict]]:
        """ATMs: availability, alarm, who robbed them (``None`` while offline)."""
        return self._section("Atms")

    def get_incidents(self) -> Optional[dict]:
        """The control room: open incidents, units, operators, timeline."""
        return self._section("Incidents")

    # Server sections ----------------------------------------------------------

    def get_staff(self) -> Optional[dict]:
        """``{ OwnerId, Staff: [...], Ranks: [...] }``."""
        return self._section("Staff")

    def get_groups(self) -> Optional[List[dict]]:
        """The server's groups and their members (``[]`` without AdvancedServer)."""
        return self._section("Groups")

    def get_bans(self, *, limit: Optional[int] = None, offset: Optional[int] = None) -> Optional[dict]:
        """One page of bans: ``{ Total, Offset, List: [...] }``. See :meth:`iter_bans`."""
        return self._section("Bans", limit=limit, offset=offset)

    def iter_bans(self, page_size: int = 1000):
        """Yield every ban, fetching pages as needed."""
        offset = 0
        while True:
            page = self.get_bans(limit=page_size, offset=offset) or {}
            bans = page.get("List") or []
            yield from bans
            offset += len(bans)
            if not bans or offset >= (page.get("Total") or 0):
                return

    def get_settings(self) -> Optional[dict]:
        """Every Server Management setting, keyed by name. Webhooks read ``"(set)"``."""
        return self._section("Settings")

    def get_catalogue(self) -> Optional[dict]:
        """Game data that only changes with an update. Cache it by ``Version``."""
        return self._section("Catalogue")

    # Logs ---------------------------------------------------------------------

    def get_killlogs(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """Kills (downs), newest first. Last 500 kept."""
        return self._section("KillLogs", since=since, limit=limit) or []

    def get_modcalls(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """Help requests, responders and resolutions, newest first. Last 300 kept."""
        return self._section("ModCalls", since=since, limit=limit) or []

    def get_radiocalls(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """Radio calls, newest first. Last 500 kept."""
        return self._section("RadioCalls", since=since, limit=limit) or []

    def get_joinlogs(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """Joins and leaves, newest first. Last 500 kept."""
        return self._section("JoinLogs", since=since, limit=limit) or []

    def get_events(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """About 100 kinds of game event, newest first. Last 1,000 kept."""
        return self._section("Events", since=since, limit=limit) or []

    def get_commandlogs(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """The newest audit log entries. Last 100 kept."""
        return self._section("CommandLogs", since=since, limit=limit) or []

    def get_command_results(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """Commands sent through the API and how they went. Last 200 kept."""
        return self._section("CommandResults", since=since, limit=limit) or []

    def get_shots(self, *, since: Optional[int] = None, limit: Optional[int] = None) -> List[dict]:
        """Every shot in the last 10 minutes, newest first."""
        return self._section("Shots", since=since, limit=limit) or []

    def get_audit(
        self,
        *,
        before: Optional[int] = None,
        category: Union[str, Iterable[str], None] = None,
        user: Union[str, int, None] = None,
        limit: Optional[int] = None,
    ) -> Optional[dict]:
        """One page of the full audit log: ``{ Entries, Next, Total }``. Slower than the rest."""
        return self._section(
            "Audit", audit_before=before, audit_category=category, audit_user=user, limit=limit
        )

    # ------------------------------------------------------------------ commands

    def run_command(self, command: str, *, check: bool = False) -> dict:
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
        result = self._post_command({"command": command})
        if check:
            _check_result(result)
        return result

    def run_commands(self, commands: Sequence[str], *, check: bool = False) -> List[dict]:
        """Run up to 10 commands in order, in one request. Returns one result per command."""
        commands = list(commands)
        if not commands:
            raise ValueError("commands must be a non-empty list")
        if len(commands) > MAX_BATCH:
            raise ValueError(f"Too many commands (max {MAX_BATCH} per batch)")
        if not all(isinstance(c, str) and c.strip() for c in commands):
            raise ValueError("Every command must be a non-empty string")
        results = self._post_command({"commands": commands})
        if isinstance(results, dict):  # defensive: a single result
            results = [results]
        if check:
            for result in results:
                _check_result(result)
        return results

    def _post_command(self, payload: dict) -> Any:
        response = self._request(
            "POST",
            "/server/command",
            limiter="command",
            json=payload,
            timeout=max(self.timeout, 15),
        )
        body = self._json(response)
        self._raise_for_error(response, body)
        return body

    def execute_command(self, command: str) -> dict:
        """Old name for :meth:`run_command`."""
        return self.run_command(command)

    def get_command(self, command_id: str) -> dict:
        """One command's result, for a command that was still ``Pending``.

        Keeps the API's old shape: lower-case ``Status`` (``succeeded``, ``failed``,
        ``pending``, ``no_result``). Results are kept for 7 days.
        """
        if not command_id:
            raise ValueError("command_id is required")
        return self._get_json(f"/server/commands/{command_id}")

    def wait_for_command(self, command_id: str, *, timeout: float = 130, interval: float = 2) -> dict:
        """Poll :meth:`get_command` until it's no longer ``pending`` (gives up after ``timeout``)."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.get_command(command_id)
            if str(result.get("Status", "")).lower() != "pending" or time.monotonic() >= deadline:
                return result
            time.sleep(interval)

    # ------------------------------------------------------------------ misc

    def get_status(self) -> dict:
        """The API's own health (``GET /status``): status, uptime and response times.
        Needs no key; don't ask more than every 30 seconds."""
        root = self.base_url.rsplit("/v1", 1)[0]
        response = self._request("GET", "/status", limiter="get", url=f"{root}/status")
        body = self._json(response)
        self._raise_for_error(response, body)
        return body

    def follow(self, *logs: str, sections: Sequence[str] = (), limit: Optional[int] = None,
               cursor: Optional[int] = None) -> "LogFollower":
        """A :class:`~oxrpy.LogFollower` that yields only new log entries. See its docs."""
        from .follower import LogFollower

        return LogFollower(self, logs or ("Events",), sections=sections, limit=limit, cursor=cursor)

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

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "OxfordAPI":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _check_result(result: dict) -> None:
    if str(result.get("Status", "")).lower() == "failed":
        raise CommandFailedError(result)


class Servers:
    """Server and live-state endpoints (kept from 1.x)."""

    def __init__(self, api: OxfordAPI) -> None:
        self.api = api

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get_") or name in ("is_online", "iter_bans"):
            return getattr(self.api, name)
        raise AttributeError(name)


class Logs:
    """Log endpoints (kept from 1.x)."""

    def __init__(self, api: OxfordAPI) -> None:
        self.api = api

    def __getattr__(self, name: str) -> Any:
        if name.startswith("get_") or name == "follow":
            return getattr(self.api, name)
        raise AttributeError(name)


class Commands:
    """Command endpoints (kept from 1.x)."""

    def __init__(self, api: OxfordAPI) -> None:
        self.api = api

    def run_command(self, command: str, *, check: bool = False) -> dict:
        return self.api.run_command(command, check=check)

    def run_commands(self, commands: Sequence[str], *, check: bool = False) -> List[dict]:
        return self.api.run_commands(commands, check=check)

    def execute_command(self, command: str) -> dict:
        return self.api.run_command(command)

    def get_command(self, command_id: str) -> dict:
        return self.api.get_command(command_id)

    def wait_for_command(self, command_id: str, **kwargs: Any) -> dict:
        return self.api.wait_for_command(command_id, **kwargs)
