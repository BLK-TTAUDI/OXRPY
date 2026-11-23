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
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterator, List, Literal, Optional, Sequence, Tuple, TypeVar, Union, overload

from . import types as t
from ._base import BASE_URL, ServerData
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

    # ------------------------------------------------------------------ servers

    def add(self, name: str, server_key: str) -> AsyncOxfordAPI:
        """Add a server under a name you choose (a guild ID, a database ID…). Returns its client,
        which you can use for that server's reads and commands. If the pool is running, the new
        server starts being followed straight away."""
        name = str(name)
        if name in self._servers:
            raise ValueError(f"There's already a server called {name!r} in the pool")
        api = AsyncOxfordAPI(server_key, client=self.client, **self._options)
        if self._shared_limiters is not None:
            api._limiters = self._shared_limiters
        api._ip_bucket = self._ip_bucket
        self._servers[name] = api
        self.failed.pop(name, None)
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
        results = await asyncio.gather(*(action(self._servers[n]) for n in chosen), return_exceptions=True)
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
            for name in list(self._tasks):
                await self._stop_server(name)

    def stop(self) -> None:
        """Make :meth:`run_forever` return once every server has finished its current poll."""
        self._stop.set()

    def _start(self, name: str) -> None:
        if name in self._tasks and not self._tasks[name].done():
            return
        stop = asyncio.Event()
        self._server_stops[name] = stop
        self._tasks[name] = asyncio.create_task(self._follow(name, stop), name=f"oxrpy:{name}")

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
        save_dir = options.get("save_dir")
        save_to = save_dir / f"{_file_name(name)}.json" if save_dir is not None else None
        try:
            await api._run(
                self._handlers,
                lambda fn, arg: fn(name, arg),
                stop=stop,
                sections=options.get("sections", ()),
                limit=options.get("limit"),
                skip_existing=options.get("skip_existing", True),
                save_to=save_to,
                adaptive=options.get("adaptive", True),
                max_idle=options.get("max_idle", 5.0),
            )
        except asyncio.CancelledError:
            raise
        except PERMANENT_ERRORS as exc:
            logger.error("Stopped following %s: %s", name, exc)
            self.failed[name] = exc
            await self._report(name, exc)
        except Exception as exc:  # noqa: BLE001 - one server's problem shouldn't stop the others
            logger.exception("Stopped following %s after an unexpected error", name)
            self.failed[name] = exc
            await self._report(name, exc)

    async def _report(self, name: str, exc: Exception) -> None:
        for fn in self._handlers.get("error"):
            try:
                result = fn(name, exc)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001
                logger.exception("Error handler %r raised", getattr(fn, "__name__", fn))

    # ------------------------------------------------------------------ lifecycle

    async def aclose(self) -> None:
        self.stop()
        for name in list(self._tasks):
            await self._stop_server(name)
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "AsyncServerPool":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"<AsyncServerPool servers={len(self)} failed={len(self.failed)}>"
