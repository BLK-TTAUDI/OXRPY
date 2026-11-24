"""Running one app across many servers: :class:`AsyncServerPool`.

For bots, CADs and dashboards that many servers use (each server's owner gives your app their
server key). One pool holds a client per server, shares one connection pool and, with an app
key, one set of rate limits (an app key's limits count across every server it calls), and runs
your handlers for every server at once.

Example::

    from oxrpy import AsyncServerPool

    pool = AsyncServerPool(app_key=os.environ["OXFD_APP_KEY"])
    pool.add("guild-1234", key_for_guild_1234)
    pool.add("guild-5678", key_for_guild_5678)

    @pool.on("Kill")
    async def on_kill(server, kill):        # handlers get the server's name first
        await post_kill(server, kill)

    await pool.run_forever(save_dir="positions/")

Needs ``pip install "oxrpy[async]"``.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, Iterator, List, Literal, Optional, Sequence, Tuple, TypeVar, Union, overload

from . import types as t
from ._base import BACKGROUND, BASE_URL, RequestInfo, ServerData
from .aio import AsyncOxfordAPI, httpx
from .events import Handlers
from .follower import PERMANENT_ERRORS
from .ratelimit import AsyncTokenBucket

logger = logging.getLogger("oxrpy")

T = TypeVar("T")

#: Every request from one IP address, whatever the key: 30 a second.
IP_REQUESTS_PER_SECOND = 30


def _file_name(name: str) -> str:
    """A safe file name for a server's saved position. Names that had to be changed get a short
    hash added, so two servers (``"a/b"`` and ``"a_b"``) never share a file."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:80] or "server"
    if safe != name:
        safe += "-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return safe


@dataclass
class ServerStats:
    """How one server in the pool is doing. See :attr:`AsyncServerPool.stats`."""

    #: Successful polls since the server was added.
    polls: int = 0
    #: Failed polls in a row (0 while all is well).
    errors: int = 0
    #: Unix time of the last successful poll, or ``None`` before the first.
    last_poll: Optional[float] = None
    #: Seconds between polls lately: how out of date this server's events and data can be.
    interval: Optional[float] = None
    #: Whether the server was online at the last poll.
    online: Optional[bool] = None
    #: Players in the server at the last poll.
    players: Optional[int] = None
    #: Why following stopped for good (e.g. the key was regenerated), or ``None``.
    failed: Optional[Exception] = None


@dataclass
class PoolStats:
    """How the whole pool is doing: ``pool.stats``. Use it to check the pool keeps up, or to
    tell your users how fresh their server's data is."""

    #: Servers in the pool.
    servers: int
    #: Servers being followed right now (``run_forever`` running and not failed).
    following: int
    #: Servers whose following stopped for good.
    failed: int
    #: Reads a second the pool keeps to across every server, or ``None`` with no limit.
    read_limit: Optional[float]
    #: Requests sent a second, over the last 10 seconds.
    requests_per_second: float
    #: Requests queued for a rate limit slot right now.
    waiting: int
    #: The average of the servers' ``interval``: typical seconds between updates.
    average_interval: Optional[float]
    #: The longest ``interval``: the most out of date any server gets.
    slowest_interval: Optional[float]
    #: Each server's :class:`ServerStats`, by name.
    per_server: Dict[str, ServerStats] = field(default_factory=dict)


class AsyncServerPool:
    """Many servers, one app. See the module docs for an example.

    Args:
        app_key: Your app key (``oxa_…``), if you have one. With ``rate_limit="auto"`` the
            pool then paces every server's requests together, within your app's limits
            (standard tier: 20 reads and 2 command requests a second, across all servers).
        rate_limit: ``"auto"`` (default), ``"none"`` for a custom or unlimited app tier, or
            seconds between requests (per server).
        timeout: Seconds to wait for a response.
        max_retries: Retries after a 429, or a network error / 500 on a read.
        base_url: Override the API base URL (for testing).
        client: Your own ``httpx.AsyncClient``, shared by every server.
    """

    def __init__(
        self,
        *,
        app_key: Optional[str] = None,
        rate_limit: Union[str, float, None] = "auto",
        timeout: float = 10,
        max_retries: int = 3,
        base_url: str = BASE_URL,
        client: Any = None,
    ) -> None:
        if httpx is None:
            raise ImportError("AsyncServerPool needs httpx: pip install \"oxrpy[async]\"")
        self._options: Dict[str, Any] = {
            "app_key": app_key, "rate_limit": rate_limit, "timeout": timeout,
            "max_retries": max_retries, "base_url": base_url,
        }
        self._owns_client = client is None
        self.client = client if client is not None else httpx.AsyncClient()
        pacing = rate_limit == "auto"
        self._shared_limiters: Optional[Dict[str, Any]] = None
        if pacing and app_key:
            shared = AsyncTokenBucket(20, 40)
            self._shared_limiters = {"data": shared, "get": shared, "command": AsyncTokenBucket(2, 5)}
        self._ip_bucket = AsyncTokenBucket(IP_REQUESTS_PER_SECOND, IP_REQUESTS_PER_SECOND) if pacing else None

        self._servers: Dict[str, AsyncOxfordAPI] = {}
        self._handlers = Handlers()
        self._tasks: Dict[str, "asyncio.Task[None]"] = {}
        self._server_stops: Dict[str, asyncio.Event] = {}
        self._stop = asyncio.Event()
        self._run_options: Optional[Dict[str, Any]] = None
        #: Servers whose polling stopped for good (e.g. their key was regenerated), with the error.
        self.failed: Dict[str, Exception] = {}
        self._stats: Dict[str, ServerStats] = {}
        self._sent: Deque[float] = deque(maxlen=100_000)

    # ------------------------------------------------------------------ servers

    def add(self, name: str, server_key: str) -> AsyncOxfordAPI:
        """Add a server under a name you choose (a guild ID, a database ID…). Returns its client,
        which you can use for that server's reads and commands. If the pool is running, the new
        server starts being followed straight away."""
        name = str(name)
        if name in self._servers:
            raise ValueError(f"There's already a server called {name!r} in the pool")
        api = self._client(server_key)
        self._servers[name] = api
        self._stats[name] = ServerStats()
        self.failed.pop(name, None)
        if self._run_options is not None:
            self._start(name)
        return api

    def _client(self, server_key: str) -> AsyncOxfordAPI:
        """A client for one server, sharing the pool's connections and rate limits."""
        api = AsyncOxfordAPI(server_key, client=self.client, **self._options)
        if self._shared_limiters is not None:
            api._limiters = self._shared_limiters
        api._ip_bucket = self._ip_bucket
        api.on_request(self._count_request)
        return api

    def _count_request(self, info: RequestInfo) -> None:
        if info.status is not None:
            self._sent.append(time.monotonic())

    async def verify(self, server_key: str) -> t.ServerInfo:
        """Check a server key before you save it, e.g. in a ``/link`` command. Returns the
        server's details (``Name``, ``OwnerId``, ``CurrentPlayers``...), so you can show which
        server it is. Uses the pool's rate limits; doesn't add the server.

        Raises:
            oxrpy.AuthenticationError: The key is wrong, was regenerated, or the server doesn't
                have the API package.
        """
        data = await self._client(server_key).get_server()
        return data["Server"]

    async def update_key(self, name: str, server_key: str) -> AsyncOxfordAPI:
        """Swap in a new server key for ``name``, e.g. after the owner regenerated theirs.
        Following carries on from where it was (from ``save_dir`` if you use one), and the
        server leaves :attr:`failed`. Returns the new client."""
        name = str(name)
        old = self._servers[name]
        await self._stop_server(name)
        api = self._client(server_key)
        api.latest = old.latest
        if getattr(old, "cursor", None) is not None:
            api.cursor = old.cursor  # type: ignore[attr-defined]
        self._servers[name] = api
        self.failed.pop(name, None)
        stats = self._stats.setdefault(name, ServerStats())
        stats.failed, stats.errors = None, 0
        if self._run_options is not None:
            self._start(name)
        return api

    async def remove(self, name: str) -> None:
        """Stop following a server and forget it."""
        api = self._servers.pop(str(name), None)
        if api is None:
            raise KeyError(name)
        await self._stop_server(str(name))
        self.failed.pop(str(name), None)
        self._stats.pop(str(name), None)

    def __getitem__(self, name: str) -> AsyncOxfordAPI:
        return self._servers[str(name)]

    def __contains__(self, name: object) -> bool:
        return str(name) in self._servers

    def __len__(self) -> int:
        return len(self._servers)

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._servers))

    @property
    def names(self) -> List[str]:
        return list(self._servers)

    # ------------------------------------------------------------------ doing things everywhere

    async def each(
        self,
        action: Callable[[AsyncOxfordAPI], Awaitable[T]],
        *,
        names: Optional[Sequence[str]] = None,
    ) -> Dict[str, Union[T, Exception]]:
        """Run ``action(api)`` for every server at once. Returns ``{name: result}``, where a
        server that failed has its exception instead of a result (one failure doesn't stop the
        others). Example: ``await pool.each(lambda api: api.get_players())``."""
        chosen = list(names) if names is not None else list(self._servers)
        # Runs behind single requests (a Discord command's lookup, say), so one big job across
        # every server doesn't hold up everyone else's.
        token = BACKGROUND.set(True)
        try:
            results = await asyncio.gather(*(action(self._servers[n]) for n in chosen), return_exceptions=True)
        finally:
            BACKGROUND.reset(token)
        return dict(zip(chosen, results))  # type: ignore[arg-type]

    async def run_command_on_all(self, command: str, *, names: Optional[Sequence[str]] = None
                                 ) -> Dict[str, Any]:
        """Run one command on every server (e.g. an announcement). Returns ``{name: result}``."""
        return await self.each(lambda api: api.run_command(command), names=names)

    # ------------------------------------------------------------------ handlers

    # Typed forms, so a type checker can check handlers: ``(server name, entry)``.
    @overload
    def on(self, key: Literal["Kill", "KillLogs"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.KillLog], Any]], Callable[[str, t.KillLog], Any]]: ...
    @overload
    def on(self, key: Literal["ModCall", "ModCalls"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.ModCall], Any]], Callable[[str, t.ModCall], Any]]: ...
    @overload
    def on(self, key: Literal["RadioCall", "RadioCalls"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.RadioCall], Any]], Callable[[str, t.RadioCall], Any]]: ...
    @overload
    def on(self, key: Literal["Join", "Leave", "JoinLogs"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.JoinLog], Any]], Callable[[str, t.JoinLog], Any]]: ...
    @overload
    def on(self, key: Literal["Command", "CommandLogs"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.CommandLog], Any]], Callable[[str, t.CommandLog], Any]]: ...
    @overload
    def on(self, key: Literal["CommandResult", "CommandResults"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.CommandResultLog], Any]], Callable[[str, t.CommandResultLog], Any]]: ...
    @overload
    def on(self, key: Literal["Shot", "Shots"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, t.Shot], Any]], Callable[[str, t.Shot], Any]]: ...
    @overload
    def on(self, key: Literal["poll", "ServerOnline", "ServerOffline", "ServerRestart"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, ServerData], Any]], Callable[[str, ServerData], Any]]: ...
    @overload
    def on(self, key: Literal["error"], /  # type: ignore[overload-overlap]
           ) -> Callable[[Callable[[str, Exception], Any]], Callable[[str, Exception], Any]]: ...
    @overload
    def on(self, key: str, /) -> Callable[[Callable[[str, t.Event], Any]], Callable[[str, t.Event], Any]]: ...
    @overload
    def on(self, *keys: Any) -> Any: ...

    def on(self, *keys: Any) -> Any:
        """Register a handler, like :meth:`OxfordAPI.on`, except handlers are called with the
        server's name first: ``async def on_kill(server, kill)``. ``error`` handlers get
        ``(server, exception)``."""
        if keys and callable(keys[-1]):
            *names, fn = keys
            self._handlers.add(names, fn)
            return fn

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self._handlers.add(keys, fn)
            return fn

        return decorator

    async def run_forever(
        self,
        *,
        sections: Sequence[str] = (),
        limit: Optional[int] = None,
        skip_existing: bool = True,
        save_dir: Union[str, Path, None] = None,
        adaptive: bool = True,
        max_idle: float = 5.0,
    ) -> None:
        """Follow every server and call the handlers until :meth:`stop` (or cancellation).

        Each server is polled on its own heartbeat. A server whose key stops working (the owner
        regenerated it, or the API package lapsed) is dropped from polling, reported to your
        ``error`` handlers, and listed in :attr:`failed`; the others carry on.

        Args:
            sections: Other sections to fetch every time, for ``poll`` handlers.
            limit: Most entries per log per request.
            skip_existing: Don't replay what was already in the logs at start (default).
            save_dir: A folder to keep each server's position in (one small JSON file per
                server), so a restart carries on where it left off.
            adaptive: Poll quiet and empty servers less often (on by default), so one app can
                follow more servers within its rate limit. Busy servers are still polled on every
                heartbeat. Turn it off to poll every server every heartbeat.
            max_idle: The slowest a quiet server is polled, in seconds (default 5).
        """
        if not self._handlers:
            raise ValueError("No handlers registered: use @pool.on('Kill') (or another event) first")
        self._stop.clear()
        self._run_options = {"sections": sections, "limit": limit, "skip_existing": skip_existing,
                             "save_dir": Path(save_dir) if save_dir is not None else None,
                             "adaptive": adaptive, "max_idle": max_idle}
        try:
            for name in list(self._servers):
                self._start(name)
            await self._stop.wait()
        finally:
            self._run_options = None
            await self._stop_all()

    def stop(self) -> None:
        """Make :meth:`run_forever` return once every server has finished its current poll."""
        self._stop.set()

    def _start(self, name: str) -> None:
        if name in self._tasks and not self._tasks[name].done():
            return
        stop = asyncio.Event()
        self._server_stops[name] = stop
        self._tasks[name] = asyncio.create_task(self._follow(name, stop), name=f"oxrpy:{name}")

    async def _stop_all(self) -> None:
        """Stop every server at once (one by one would keep the rest polling meanwhile)."""
        await asyncio.gather(*(self._stop_server(name) for name in list(self._tasks)))

    async def _stop_server(self, name: str) -> None:
        stop = self._server_stops.pop(name, None)
        task = self._tasks.pop(name, None)
        if stop is not None:
            stop.set()
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)
            except asyncio.TimeoutError:
                task.cancel()
            except Exception:  # noqa: BLE001 - already reported by _follow
                pass

    async def _follow(self, name: str, stop: asyncio.Event) -> None:
        options = self._run_options or {}
        api = self._servers[name]
        stats = self._stats.setdefault(name, ServerStats())
        save_dir = options.get("save_dir")
        save_to = save_dir / f"{_file_name(name)}.json" if save_dir is not None else None
        # Carry on from a position kept in memory (after update_key) unless save_dir has one.
        cursor = getattr(api, "cursor", None) if save_to is None else None

        def polled(data: ServerData) -> None:
            now = time.time()
            if stats.last_poll is not None:
                gap = now - stats.last_poll
                stats.interval = gap if stats.interval is None else stats.interval * 0.7 + gap * 0.3
            stats.last_poll = now
            stats.polls += 1
            stats.errors = 0
            stats.online = bool(data.get("Online"))
            server = data.get("Server")
            stats.players = server.get("CurrentPlayers") if isinstance(server, dict) else None

        async def poll_failed(exc: Exception) -> None:
            stats.errors += 1

        try:
            await api._run(
                self._handlers,
                lambda fn, arg: fn(name, arg),
                stop=stop,
                sections=options.get("sections", ()),
                limit=options.get("limit"),
                cursor=cursor,
                skip_existing=options.get("skip_existing", True),
                save_to=save_to,
                on_error=poll_failed,
                on_poll=polled,
                adaptive=options.get("adaptive", True),
                max_idle=options.get("max_idle", 5.0),
            )
        except asyncio.CancelledError:
            raise
        except PERMANENT_ERRORS as exc:
            logger.error("Stopped following %s: %s", name, exc)
            self.failed[name] = stats.failed = exc
            await self._report(name, exc)
        except Exception as exc:  # noqa: BLE001 - one server's problem shouldn't stop the others
            logger.exception("Stopped following %s after an unexpected error", name)
            self.failed[name] = stats.failed = exc
            await self._report(name, exc)

    async def _report(self, name: str, exc: Exception) -> None:
        for fn in self._handlers.get("error"):
            try:
                result = fn(name, exc)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.exception("Error handler %r raised", getattr(fn, "__name__", fn))

    # ------------------------------------------------------------------ stats

    @property
    def read_limit(self) -> Optional[float]:
        """Reads a second the pool keeps to across every server (``None``: no limit). Without
        an app key that's the per-IP limit; with one, your app's limit (which follows what
        Oxford reports, so custom tiers are picked up), capped by the per-IP limit."""
        rates = []
        if self._shared_limiters is not None:
            rates.append(self._shared_limiters["data"].rate)
        if self._ip_bucket is not None:
            rates.append(self._ip_bucket.rate)
        return min(rates) if rates else None

    @property
    def stats(self) -> PoolStats:
        """How the pool is keeping up: overall figures, and each server's
        :class:`ServerStats` in ``per_server``. Example::

            stats = pool.stats
            print(f"{stats.following} servers, updated about every {stats.average_interval:.1f}s")
        """
        now = time.monotonic()
        recent = sum(1 for sent in self._sent if sent >= now - 10)
        intervals = [s.interval for s in self._stats.values() if s.interval is not None and s.failed is None]
        buckets = [b for b in ((self._shared_limiters or {}).get("data"), self._ip_bucket) if b is not None]
        following = sum(1 for name, task in self._tasks.items() if not task.done() and name not in self.failed)
        return PoolStats(
            servers=len(self._servers),
            following=following,
            failed=len(self.failed),
            read_limit=self.read_limit,
            requests_per_second=recent / 10,
            waiting=max((b.waiting for b in buckets), default=0),
            average_interval=sum(intervals) / len(intervals) if intervals else None,
            slowest_interval=max(intervals) if intervals else None,
            per_server={name: ServerStats(**vars(s)) for name, s in self._stats.items()},
        )

    # ------------------------------------------------------------------ lifecycle

    async def aclose(self) -> None:
        self.stop()
        await self._stop_all()
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "AsyncServerPool":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"<AsyncServerPool servers={len(self)} failed={len(self.failed)}>"
