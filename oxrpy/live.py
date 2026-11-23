"""``api.latest``: the newest copy of the server's live state, kept in memory.

Every time the client gets data from ``GET /v1/server`` (from ``run_forever``, ``follow``, a
helper like ``get_players()``, or ``get_server_data``), the sections in that response are stored
here with the time they arrived. Reading them costs no request, which matters when you're only
allowed one ``GET /v1/server`` a second.

Typical use: keep ``run_forever(sections=["Players", "Vehicles"])`` running, and answer bot
commands from ``api.latest.players``. Check ``api.latest.age("Players")`` if freshness matters.

Logs aren't kept here (each response only has the *new* entries), and nor are ``Bans`` and
``Audit``, which come in pages.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from . import types as t

#: Sections that aren't a full picture on their own, so aren't kept.
NOT_KEPT = frozenset({
    "KillLogs", "ModCalls", "RadioCalls", "JoinLogs", "Events", "CommandLogs", "CommandResults",
    "Shots", "Bans", "Audit",
})

#: Fields every ``GET /v1/server`` response has.
TOP_LEVEL = ("Online", "LastHeartbeat", "NextHeartbeat", "Cursor", "Server")


class LiveState:
    """The newest copy of each section the client has seen. See the module docs."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()
        #: Unix time of the last update, or ``None`` before the first.
        self.updated_at: Optional[float] = None

    def update(self, data: Dict[str, Any]) -> None:
        """Store the sections in a ``GET /v1/server`` response (done for you)."""
        now = time.monotonic()
        with self._lock:
            for key, value in data.items():
                if key in NOT_KEPT:
                    continue
                self._data[key] = value
                self._seen[key] = now
            self.updated_at = time.time()

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._seen.clear()
            self.updated_at = None

    def get(self, section: str, default: Any = None) -> Any:
        """A section by name (``"Players"``, ``"World"``…), or ``default`` if not seen yet."""
        with self._lock:
            return self._data.get(section, default)

    def __contains__(self, section: object) -> bool:
        return section in self._seen

    def age(self, section: str) -> Optional[float]:
        """Seconds since ``section`` was last received, or ``None`` if it never has been."""
        with self._lock:
            seen = self._seen.get(section)
        return None if seen is None else time.monotonic() - seen

    def is_fresh(self, section: str, max_age: float) -> bool:
        """Whether ``section`` arrived within the last ``max_age`` seconds."""
        age = self.age(section)
        return age is not None and age <= max_age

    @property
    def sections(self) -> List[str]:
        """Names of the sections held."""
        with self._lock:
            return sorted(self._data)

    # The common ones, typed --------------------------------------------------

    @property
    def online(self) -> Optional[bool]:
        """Whether the server was online at the last response (``None`` before any)."""
        value = self.get("Online")
        return None if value is None else bool(value)

    @property
    def server(self) -> Optional[t.ServerInfo]:
        return self.get("Server")

    @property
    def players(self) -> Optional[List[t.Player]]:
        """``None`` if never fetched, or while the server is offline."""
        return self.get("Players")

    @property
    def vehicles(self) -> Optional[List[t.Vehicle]]:
        return self.get("Vehicles")

    @property
    def world(self) -> Optional[t.World]:
        return self.get("World")

    @property
    def teams(self) -> Optional[t.Teams]:
        return self.get("Teams")

    @property
    def queue(self) -> Optional[List[t.QueueEntry]]:
        return self.get("Queue")

    @property
    def robberies(self) -> Optional[List[t.Robbery]]:
        return self.get("Robberies")

    @property
    def incidents(self) -> Optional[t.Incidents]:
        return self.get("Incidents")

    @property
    def staff(self) -> Optional[t.Staff]:
        return self.get("Staff")

    @property
    def groups(self) -> Optional[List[t.Group]]:
        return self.get("Groups")

    def __repr__(self) -> str:
        return f"<LiveState sections={self.sections}>"
