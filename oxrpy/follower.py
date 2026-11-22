"""Follow the server's logs with ``Since``/``Cursor``, getting each entry once."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Sequence, Tuple

from .client import LOG_SECTIONS, ServerData, _section_name

if TYPE_CHECKING:
    from .client import OxfordAPI


class LogFollower:
    """Polls ``GET /v1/server`` with ``Since`` and hands back only entries you haven't seen.

    Handles the API's cursor rules for you: entries are returned oldest first, entries you've
    already handled (by ``Seq``, per log) are skipped, and the request is timed for just after
    the server's next heartbeat (slowly while it's offline).

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

    def __init__(
        self,
        api: "OxfordAPI",
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

    def poll(self) -> Tuple[ServerData, Dict[str, List[dict]]]:
        """Make one request. Returns ``(data, new)`` where ``new[log]`` lists unseen entries, oldest first."""
        data = self.api.get_server_data(*self.logs, *self.sections, since=self.cursor, limit=self.limit)
        assert data is not None
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
        return data, new

    def next_delay(self, data: Optional[ServerData] = None, *, offline_delay: float = 30) -> float:
        """Seconds to wait before the next poll: just after ``NextHeartbeat``, or ``offline_delay``."""
        data = data if data is not None else self.last
        next_beat = data.get("NextHeartbeat") if data else None
        if not next_beat:
            return offline_delay
        return max(1.0, next_beat - time.time() + 0.5)

    def __iter__(self) -> Iterator[Tuple[ServerData, Dict[str, List[dict]]]]:
        """Poll forever, sleeping between requests. Break out of the loop to stop."""
        while True:
            data, new = self.poll()
            yield data, new
            time.sleep(self.next_delay(data))
