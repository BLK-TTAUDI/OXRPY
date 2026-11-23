"""The Oxford Response private server API client (sync, using ``requests``)."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple

import requests

from ._base import (  # noqa: F401  (re-exported for 2.0 imports)
    AUDIT_CATEGORIES,
    BASE_URL,
    LOG_SECTIONS,
    MAX_BATCH,
    SECTIONS,
    BaseClient,
    Commands,
    Logs,
    ServerData,
    Servers,
    _decode,
    _section_name,
    _Spec,
    logger,
)
from .errors import OxfordAPIError, RateLimitError
from .events import ServerWatcher, dispatch_plan
from .follower import LogFollower
from ._signatures import SyncSignatures
from .types import Ban, CommandResult, CommandStatus
from .ratelimit import TokenBucket
from .sync import CommandWindow, chunk


class OxfordAPI(SyncSignatures, BaseClient):
    """Client for the Oxford Response private server API (https://docs.oxfd.re).

    For asyncio code (discord.py and the like) use :class:`~oxrpy.AsyncOxfordAPI`, which has
    the same methods.

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

    _bucket_class = TokenBucket

    def __init__(self, server_key: Optional[str] = None, *, session: Optional[requests.Session] = None,
                 **kwargs: Any) -> None:
        super().__init__(server_key, **kwargs)
        self.session = session or requests.Session()
        self.session.headers.update(self.headers)
        self._stop = threading.Event()
        self._command_window = CommandWindow()

    # ------------------------------------------------------------------ transport

    def _execute(self, spec: _Spec) -> Any:
        bucket = self._limiters.get(spec.limiter)
        attempt = 0
        while True:
            if bucket is not None and not bucket.acquire(timeout=60):
                raise RateLimitError(f"Timed out waiting for a rate limit slot for {spec.path}")
            try:
                response = self.session.request(
                    spec.method,
                    self._url(spec),
                    params=spec.params,
                    json=spec.json,
                    headers=spec.headers,
                    timeout=spec.timeout or self.timeout,
                )
            except requests.RequestException as exc:
                delay = self._network_retry_delay(spec, attempt)
                if delay is None:
                    raise self._network_error(spec, exc, isinstance(exc, requests.Timeout)) from exc
                attempt += 1
                time.sleep(delay)
                continue

            body = _decode(response.content)
            delay = self._response_retry_delay(spec, response.status_code, response.headers, body, attempt)
            if delay is not None:
                attempt += 1
                if response.status_code == 429:
                    if bucket is not None:
                        bucket.drain()
                    logger.warning("Rate limited on %s %s, retrying in %.1fs", spec.method, spec.path, delay)
                time.sleep(delay)
                continue
            logger.debug("%s %s -> %s", spec.method, spec.path, response.status_code)
            return self._handle(spec, response.status_code, response.headers, body)

    def _call(self, spec: _Spec, transform: Optional[Callable[[Any], Any]] = None) -> Any:
        value = self._execute(spec)
        return transform(value) if transform is not None else value

    def _ready(self, value: Any) -> Any:
        return value

    # ------------------------------------------------------------------ many commands

    def run_many(self, commands: Sequence[str], *, check: bool = False) -> List[CommandResult]:
        """Run any number of commands, in order, as fast as the game allows.

        Sends them in batches of up to 10 and waits when needed to stay under the game's
        15 commands every 10 seconds. Returns one result per command, in the same order.
        With ``check=True`` it stops at the first failed command and raises
        :class:`CommandFailedError`.
        """
        commands = list(commands)
        results: List[CommandResult] = []
        for batch in chunk(commands, MAX_BATCH):
            wait = self._command_window.wait_time(len(batch))
            if wait:
                logger.info("Waiting %.1fs to stay under the game's command limit", wait)
                time.sleep(wait)
            batch_results = self.run_commands(batch, check=check)
            self._command_window.record(len(batch))
            results.extend(batch_results)
        return results

    def sync_staff(self, desired: Mapping[Any, Optional[str]], *, remove_others: bool = False
                   ) -> List[Tuple[str, CommandResult]]:
        """Make the staff match ``desired`` (user ID -> rank, or ``None`` to remove), sending
        only the changes. Returns ``(command, result)`` pairs; an empty list means nothing
        needed changing. Use :meth:`plan_staff_sync` to see the commands without running them.

        ``remove_others=True`` also unranks staff not in ``desired`` (never the owner)."""
        commands = self.plan_staff_sync(desired, remove_others=remove_others)
        return list(zip(commands, self.run_many(commands)))

    def sync_group(self, group: str, members: Iterable[Any], *, remove_others: bool = True
                   ) -> List[Tuple[str, CommandResult]]:
        """Make ``group`` (name or Id) contain exactly ``members`` (user IDs), sending only the
        changes. Returns ``(command, result)`` pairs. ``remove_others=False`` only adds."""
        commands = self.plan_group_sync(group, members, remove_others=remove_others)
        return list(zip(commands, self.run_many(commands)))

    # ------------------------------------------------------------------ loops

    def iter_bans(self, page_size: int = 1000) -> Iterator[Ban]:
        """Yield every ban, fetching pages as needed."""
        offset = 0
        while True:
            page = self.get_bans(limit=page_size, offset=offset) or {}
            bans = page.get("List") or []
            yield from bans
            offset += len(bans)
            if not bans or offset >= (page.get("Total") or 0):
                return

    def wait_for_command(self, command_id: str, *, timeout: float = 130, interval: float = 2) -> CommandStatus:
        """Poll :meth:`get_command` until it's no longer ``pending`` (gives up after ``timeout``)."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.get_command(command_id)
            if str(result.get("Status", "")).lower() != "pending" or time.monotonic() >= deadline:
                return result
            time.sleep(interval)

    def follow(self, *logs: str, sections: Sequence[str] = (), limit: Optional[int] = None,
               cursor: Optional[int] = None) -> LogFollower:
        """A :class:`~oxrpy.LogFollower` that yields only new log entries. See its docs."""
        return LogFollower(self, logs or ("Events",), sections=sections, limit=limit, cursor=cursor)

    def run_forever(
        self,
        *,
        sections: Sequence[str] = (),
        limit: Optional[int] = None,
        cursor: Optional[int] = None,
        skip_existing: bool = True,
    ) -> None:
        """Poll the server and call the handlers registered with :meth:`on`, until :meth:`stop`.

        Entries from every log are passed to handlers oldest first. A handler that raises is
        logged and skipped, and request errors are retried (see :class:`LogFollower`), so one
        bad moment doesn't stop your bot. A wrong key still raises.

        Args:
            sections: Other sections to fetch every time (e.g. ``["Players"]``), for ``poll`` handlers.
            limit: Most entries per log per request.
            cursor: Resume from a saved cursor (then nothing is skipped).
            skip_existing: Don't replay the entries that were already in the logs when you
                started. Default ``True``.
        """
        if not self._handlers:
            raise ValueError("No handlers registered: use @api.on('Kill') (or another event) first")
        follower = LogFollower(self, self._handlers.logs_needed(), sections=sections, limit=limit,
                               cursor=cursor)
        skip = skip_existing and cursor is None
        watcher = ServerWatcher()
        self._stop.clear()
        for data, new in follower.iter(stop=self._stop, on_error=self._dispatch_error):
            for fn, arg in dispatch_plan(self._handlers, watcher, data, new, skip):
                self._safely(fn, arg)
            skip = False
        self.cursor = follower.cursor

    def stop(self) -> None:
        """Make :meth:`run_forever` return after the current poll (safe from any thread)."""
        self._stop.set()

    def _safely(self, fn: Callable[..., Any], arg: Any) -> None:
        try:
            fn(arg)
        except Exception:  # noqa: BLE001 - one bad handler shouldn't stop the bot
            logger.exception("Handler %r raised", getattr(fn, "__name__", fn))

    def _dispatch_error(self, exc: OxfordAPIError) -> None:
        for fn in self._handlers.get("error"):
            self._safely(fn, exc)

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "OxfordAPI":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
