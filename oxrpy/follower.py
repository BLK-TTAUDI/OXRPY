"""Follow the server's logs with ``Since``/``Cursor``, getting each entry once."""

from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from ._base import LOG_SECTIONS, ServerData, _section_name
from .errors import (
    AuthenticationError,
    BadRequestError,
    EndpointRemovedError,
    NotFoundError,
    OxfordAPIError,
    RateLimitError,
)

if TYPE_CHECKING:
    from .client import OxfordAPI

logger = logging.getLogger("oxrpy")

#: Errors that won't fix themselves by waiting, so following stops and raises them.
PERMANENT_ERRORS = (AuthenticationError, BadRequestError, NotFoundError, EndpointRemovedError)

MAX_ERROR_DELAY = 60.0


def error_delay(exc: OxfordAPIError, failures: int) -> float:
    """How long to wait after the ``failures``-th failure in a row."""
    if isinstance(exc, RateLimitError) and exc.retry_after:
        return max(1.0, exc.retry_after)
    return min(MAX_ERROR_DELAY, 2.0 ** failures)


class _FollowerBase:
    def __init__(
        self,
        api: Any,
        logs: Sequence[str] = ("Events",),
        *,
        sections: Sequence[str] = (),
        limit: Optional[int] = None,
        cursor: Optional[int] = None,
    ) -> None:
        self.api = api
        self.logs = [_section_name(log) for log in logs]
        unknown = [log for log in self.logs if log not in LOG_SECTIONS]
        if unknown:
            raise ValueError(f"Not log sections: {', '.join(unknown)} (choose from {', '.join(LOG_SECTIONS)})")
        self.sections = [_section_name(s) for s in sections if _section_name(s) not in self.logs]
        self.limit = limit
        self.cursor = cursor
        self.handled: Dict[str, int] = {}
        self.last: Optional[ServerData] = None
        self.failures = 0

    def _request_args(self) -> Tuple[List[str], Dict[str, Any]]:
        return [*self.logs, *self.sections], {"since": self.cursor, "limit": self.limit}

    def _process(self, data: ServerData) -> Dict[str, List[dict]]:
        new: Dict[str, List[dict]] = {}
        for log in self.logs:
            entries = data.get(log) or []
            fresh = []
            for entry in reversed(entries):  # the API sends newest first
                seq = entry.get("Seq")
                if seq is not None and seq <= self.handled.get(log, -1):
                    continue
                if seq is not None:
                    self.handled[log] = seq
                fresh.append(entry)
            new[log] = fresh
        if data.get("Cursor") is not None:
            self.cursor = data["Cursor"]
        self.last = data
        self.failures = 0
        return new

    def _after_error(self, exc: OxfordAPIError, retry: bool) -> float:
        if not retry or isinstance(exc, PERMANENT_ERRORS):
            raise exc
        self.failures += 1
        delay = error_delay(exc, self.failures)
        logger.warning("Polling failed (%s); trying again in %.0fs", exc, delay)
        return delay

    def next_delay(self, data: Optional[ServerData] = None, *, offline_delay: float = 30) -> float:
        """Seconds to wait before the next poll: just after ``NextHeartbeat``, or ``offline_delay``."""
        data = data if data is not None else self.last
        next_beat = data.get("NextHeartbeat") if data else None
        if not next_beat:
            return offline_delay
        return max(1.0, next_beat - time.time() + 0.5)


class LogFollower(_FollowerBase):
    """Polls ``GET /v1/server`` with ``Since`` and hands back only entries you haven't seen.

    Handles the API's cursor rules for you: entries are returned oldest first, entries you've
    already handled (by ``Seq``, per log) are skipped, and the request is timed for just after
    the server's next heartbeat (slowly while it's offline).

    Looping over it keeps going through network problems, rate limits and API errors, waiting
    a little longer after each failure in a row (up to a minute). It only stops for errors that
    waiting won't fix, like a wrong key, and raises those.

    An entry that changes (a mod call resolved, a command result arriving, a shot gaining its
    hit) comes again with a higher ``Seq`` and the same ``Id``: replace what you have by ``Id``.

    Example::

        for data, new in api.follow("Events", "KillLogs", sections=["Players"]):
            for event in new["Events"]:
                print(event["Type"], event)

    Args:
        api: The client.
        logs: Log sections to follow (``Events``, ``KillLogs``, ``ModCalls``, ``Shots``…).
        sections: Other sections to fetch on every poll (e.g. ``Players``).
        limit: Most entries per log per request (API default 100, max 500).
        cursor: Resume from a ``Cursor`` you saved. ``None`` starts with the newest ``limit``
            entries of each log.
    """

    api: "OxfordAPI"

    def poll(self) -> Tuple[ServerData, Dict[str, List[dict]]]:
        """Make one request. Returns ``(data, new)`` where ``new[log]`` lists unseen entries,
        oldest first. Errors are raised, not retried."""
        names, kwargs = self._request_args()
        data = self.api.get_server_data(*names, **kwargs)
        assert data is not None
        return data, self._process(data)

    def iter(
        self,
        *,
        retry: bool = True,
        stop: Optional[threading.Event] = None,
        on_error: Optional[Callable[[OxfordAPIError], Any]] = None,
    ) -> Iterator[Tuple[ServerData, Dict[str, List[dict]]]]:
        """Poll until ``stop`` is set (or forever). With ``retry=False`` the first error is raised."""

        def wait(seconds: float) -> None:
            if stop is not None:
                stop.wait(seconds)
            else:
                time.sleep(seconds)

        while stop is None or not stop.is_set():
            try:
                data, new = self.poll()
            except OxfordAPIError as exc:
                delay = self._after_error(exc, retry)
                if on_error is not None:
                    on_error(exc)
                wait(delay)
                continue
            yield data, new
            wait(self.next_delay(data))

    def __iter__(self) -> Iterator[Tuple[ServerData, Dict[str, List[dict]]]]:
        return self.iter()
