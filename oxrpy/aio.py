"""The asyncio client, for discord.py and other async code. Needs ``pip install oxrpy[async]``.

Every method is the same as :class:`~oxrpy.OxfordAPI`'s, but you ``await`` it::

    from oxrpy import AsyncOxfordAPI

    async with AsyncOxfordAPI(key) as api:
        players = await api.get_players()
        await api.kick("dxrkrider", "Exploiting")
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, AsyncIterator, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from ._base import BASE_URL, MAX_BATCH, BaseClient, ServerData, _decode, _Spec, logger
from .errors import OxfordAPIError, RateLimitError
from .events import Handlers, ServerWatcher, dispatch_plan
from .follower import _FollowerBase
from ._signatures import AsyncSignatures
from .types import Ban, CommandResult, CommandStatus
from .ratelimit import AsyncTokenBucket
from .sync import CommandWindow, chunk

try:
    import httpx
except ImportError:  # pragma: no cover - checked when the client is created
    httpx = None  # type: ignore[assignment]


class AsyncOxfordAPI(AsyncSignatures, BaseClient):
    """Async client for the Oxford Response private server API. Every method of
    :class:`~oxrpy.OxfordAPI` is here too; you ``await`` them.

    Use it with ``async with``, or call ``await api.aclose()`` when you're done.

    Args:
        server_key: Your server's API key (Server Management > External > API Key).
        app_key: Optional app key (``oxa_…``), sent alongside the server key.
        timeout: Seconds to wait for a response (commands always get at least 15).
        rate_limit: ``"auto"`` (default), ``"none"``, or seconds between requests.
        max_retries: Retries after a 429, or a network error / 500 on a read.
        base_url: Override the API base URL (for testing).
        client: Use your own ``httpx.AsyncClient``.
        global_key: Removed in 2.0; passing it warns and treats it as ``app_key``.
        server_id: No longer used; passing it warns.
    """

    _bucket_class = AsyncTokenBucket

    def __init__(
        self,
        server_key: Optional[str] = None,
        *,
        app_key: Optional[str] = None,
        timeout: float = 10,
        rate_limit: Union[str, float, None] = "auto",
        max_retries: int = 3,
        base_url: str = BASE_URL,
        client: Any = None,
        global_key: Optional[str] = None,
        server_id: Optional[str] = None,
    ) -> None:
        if httpx is None:
            raise ImportError("AsyncOxfordAPI needs httpx: pip install \"oxrpy[async]\"")
        super().__init__(server_key, app_key=app_key, timeout=timeout, rate_limit=rate_limit,
                         max_retries=max_retries, base_url=base_url, global_key=global_key,
                         server_id=server_id)
        self._owns_client = client is None
        self.client = client if client is not None else httpx.AsyncClient()
        self._stop = asyncio.Event()
        self._command_window = CommandWindow()

    # ------------------------------------------------------------------ transport

    async def _execute(self, spec: _Spec) -> Any:
        bucket = self._limiters.get(spec.limiter)
        headers = dict(self.headers)
        if spec.headers:
            headers.update(spec.headers)
        attempt = 0
        while True:
            if bucket is not None and not await bucket.acquire(timeout=60):
                raise RateLimitError(f"Timed out waiting for a rate limit slot for {spec.path}")
            if self._ip_bucket is not None and not await self._ip_bucket.acquire(timeout=60):
                raise RateLimitError(f"Timed out waiting for a rate limit slot for {spec.path}")
            try:
                response = await self.client.request(
                    spec.method,
                    self._url(spec),
                    params=spec.params,
                    json=spec.json,
                    headers=headers,
                    timeout=spec.timeout or self.timeout,
                )
            except httpx.HTTPError as exc:
                delay = self._network_retry_delay(spec, attempt)
                if delay is None:
                    raise self._network_error(spec, exc, isinstance(exc, httpx.TimeoutException)) from exc
                attempt += 1
                await asyncio.sleep(delay)
                continue

            body = _decode(response.content)
            delay = self._response_retry_delay(spec, response.status_code, response.headers, body, attempt)
            if delay is not None:
                attempt += 1
                if response.status_code == 429:
                    if bucket is not None:
                        bucket.drain()
                    logger.warning("Rate limited on %s %s, retrying in %.1fs", spec.method, spec.path, delay)
                await asyncio.sleep(delay)
                continue
            logger.debug("%s %s -> %s", spec.method, spec.path, response.status_code)
            return self._handle(spec, response.status_code, response.headers, body)

    def _call(self, spec: _Spec, transform: Optional[Callable[[Any], Any]] = None) -> Any:
        async def run() -> Any:
            value = await self._execute(spec)
            return transform(value) if transform is not None else value

        return run()

    def _ready(self, value: Any) -> Any:
        async def done() -> Any:
            return value

        return done()

    # ------------------------------------------------------------------ many commands

    async def run_many(self, commands: Sequence[str], *, check: bool = False) -> List[CommandResult]:
        """Run any number of commands, in order, as fast as the game allows (batches of 10,
        staying under 15 every 10 seconds). Same as :meth:`OxfordAPI.run_many`."""
        commands = list(commands)
        results: List[CommandResult] = []
        for batch in chunk(commands, MAX_BATCH):
            wait = self._command_window.wait_time(len(batch))
            if wait:
                logger.info("Waiting %.1fs to stay under the game's command limit", wait)
                await asyncio.sleep(wait)
            batch_results = await self.run_commands(batch, check=check)
            self._command_window.record(len(batch))
            results.extend(batch_results)
        return results

    async def sync_staff(self, desired: Mapping[Any, Optional[str]], *, remove_others: bool = False
                         ) -> List[Tuple[str, CommandResult]]:
        """Make the staff match ``desired``, sending only the changes. Same as
        :meth:`OxfordAPI.sync_staff`."""
        commands = await self.plan_staff_sync(desired, remove_others=remove_others)
        return list(zip(commands, await self.run_many(commands)))

    async def sync_group(self, group: str, members: Iterable[Any], *, remove_others: bool = True
                         ) -> List[Tuple[str, CommandResult]]:
        """Make ``group`` contain exactly ``members``, sending only the changes. Same as
        :meth:`OxfordAPI.sync_group`."""
        commands = await self.plan_group_sync(group, members, remove_others=remove_others)
        return list(zip(commands, await self.run_many(commands)))

    # ------------------------------------------------------------------ loops

    async def iter_bans(self, page_size: int = 1000) -> AsyncIterator[Ban]:
        """``async for ban in api.iter_bans():`` every ban, fetching pages as needed."""
        offset = 0
        while True:
            page = await self.get_bans(limit=page_size, offset=offset) or {}
            bans = page.get("List") or []
            for ban in bans:
                yield ban
            offset += len(bans)
            if not bans or offset >= (page.get("Total") or 0):
                return

    async def wait_for_command(self, command_id: str, *, timeout: float = 130, interval: float = 2) -> CommandStatus:
        """Poll :meth:`get_command` until it's no longer ``pending`` (gives up after ``timeout``)."""
        deadline = time.monotonic() + timeout
        while True:
            result = await self.get_command(command_id)
            if str(result.get("Status", "")).lower() != "pending" or time.monotonic() >= deadline:
                return result
            await asyncio.sleep(interval)

    def follow(self, *logs: str, sections: Sequence[str] = (), limit: Optional[int] = None,
               cursor: Optional[int] = None, save_to: Any = None) -> "AsyncLogFollower":
        """An :class:`AsyncLogFollower`: ``async for data, new in api.follow("Events"):``

        ``save_to`` (a file path, or an object with ``load``/``save``) remembers the position
        across restarts. See :mod:`oxrpy.state`."""
        return AsyncLogFollower(self, logs or ("Events",), sections=sections, limit=limit, cursor=cursor,
                                save_to=save_to)

    async def run_forever(
        self,
        *,
        sections: Sequence[str] = (),
        limit: Optional[int] = None,
        cursor: Optional[int] = None,
        skip_existing: bool = True,
        save_to: Any = None,
    ) -> None:
        """Poll and call the handlers registered with :meth:`on` until :meth:`stop` (or the task
        is cancelled). Handlers can be plain functions or ``async def``. In discord.py, start it
        from ``setup_hook`` with ``asyncio.create_task(api.run_forever())``.

        Same behaviour and arguments as :meth:`OxfordAPI.run_forever`, including ``save_to``.
        """
        if not self._handlers:
            raise ValueError("No handlers registered: use @api.on('Kill') (or another event) first")
        self._stop.clear()
        await self._run(
            self._handlers,
            lambda fn, arg: fn(arg),
            stop=self._stop,
            sections=sections,
            limit=limit,
            cursor=cursor,
            skip_existing=skip_existing,
            save_to=save_to,
        )

    async def _run(
        self,
        handlers: Handlers,
        invoke: Callable[[Callable[..., Any], Any], Any],
        *,
        stop: asyncio.Event,
        sections: Sequence[str] = (),
        limit: Optional[int] = None,
        cursor: Optional[int] = None,
        skip_existing: bool = True,
        save_to: Any = None,
        on_error: Optional[Callable[[OxfordAPIError], Any]] = None,
    ) -> None:
        """The polling loop behind :meth:`run_forever` (and :class:`~oxrpy.AsyncServerPool`).
        ``invoke(fn, arg)`` calls one handler."""
        follower = AsyncLogFollower(self, handlers.logs_needed(), sections=sections, limit=limit,
                                    cursor=cursor, save_to=save_to)
        skip = skip_existing and follower.cursor is None
        watcher = ServerWatcher()

        async def call(fn: Callable[..., Any], arg: Any) -> None:
            try:
                result = invoke(fn, arg)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # noqa: BLE001 - one bad handler shouldn't stop the bot
                logger.exception("Handler %r raised", getattr(fn, "__name__", fn))

        async def errored(exc: OxfordAPIError) -> None:
            if on_error is not None:
                await on_error(exc)
            for fn in handlers.get("error"):
                await call(fn, exc)

        async for data, new in follower.iter(stop=stop, on_error=errored):
            for fn, arg in dispatch_plan(handlers, watcher, data, new, skip):
                await call(fn, arg)
            skip = False
        self.cursor = follower.cursor

    def stop(self) -> None:
        """Make :meth:`run_forever` return after the current poll."""
        self._stop.set()

    # ------------------------------------------------------------------ lifecycle

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> "AsyncOxfordAPI":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()


class AsyncLogFollower(_FollowerBase):
    """The async version of :class:`~oxrpy.LogFollower`::

    async for data, new in api.follow("Events", "KillLogs"):
        ...
    """

    api: AsyncOxfordAPI

    async def poll(self) -> Tuple[ServerData, Dict[str, List[dict]]]:
        """Make one request. Errors are raised, not retried."""
        names, kwargs = self._request_args()
        data = await self.api.get_server_data(*names, **kwargs)
        assert data is not None
        return data, self._process(data)

    async def iter(
        self,
        *,
        retry: bool = True,
        stop: Optional[asyncio.Event] = None,
        on_error: Optional[Callable[[OxfordAPIError], Any]] = None,
    ) -> AsyncIterator[Tuple[ServerData, Dict[str, List[dict]]]]:
        """Poll until ``stop`` is set (or forever). With ``retry=False`` the first error is raised."""

        async def wait(seconds: float) -> None:
            if stop is None:
                await asyncio.sleep(seconds)
                return
            try:
                await asyncio.wait_for(stop.wait(), timeout=seconds)
            except asyncio.TimeoutError:
                pass

        while stop is None or not stop.is_set():
            try:
                data, new = await self.poll()
            except OxfordAPIError as exc:
                delay = self._after_error(exc, retry)
                if on_error is not None:
                    result = on_error(exc)
                    if inspect.isawaitable(result):
                        await result
                await wait(delay)
                continue
            yield data, new
            self.save()  # only once the caller has dealt with this poll
            await wait(self.next_delay(data))

    def __aiter__(self) -> AsyncIterator[Tuple[ServerData, Dict[str, List[dict]]]]:
        return self.iter()
