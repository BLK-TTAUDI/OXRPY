"""Handler registry for ``api.on(...)`` and ``api.run_forever()``."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, Iterable, List, Tuple

# Log names, so this module doesn't import the client.
_LOGS = {
    name.lower(): name
    for name in ("KillLogs", "ModCalls", "RadioCalls", "JoinLogs", "Events", "CommandLogs",
                 "CommandResults", "Shots")
}

#: Entry ``Type`` -> the log it comes from. Any other type is a game event, in ``Events``.
TYPE_LOGS = {
    "kill": "KillLogs",
    "modcall": "ModCalls",
    "radiocall": "RadioCalls",
    "join": "JoinLogs",
    "leave": "JoinLogs",
    "command": "CommandLogs",
    "commandresult": "CommandResults",
    "shot": "Shots",
}

#: Special keys that aren't entries.
SPECIAL = ("poll", "error")


class Handlers:
    """Maps keys (entry types, log names, ``poll``, ``error``) to handler functions."""

    def __init__(self) -> None:
        self._by_key: Dict[str, List[Callable[..., Any]]] = defaultdict(list)

    def add(self, keys: Iterable[Any], fn: Callable[..., Any]) -> None:
        keys = list(keys)
        if not keys:
            raise ValueError("on() needs at least one event type or log name, e.g. on('Kill')")
        if not callable(fn):
            raise TypeError("handler must be callable")
        for key in keys:
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"Not an event type or log name: {key!r}")
            self._by_key[key.strip().lower()].append(fn)

    def get(self, key: str) -> List[Callable[..., Any]]:
        return list(self._by_key.get(key.lower(), ()))

    def __bool__(self) -> bool:
        return any(self._by_key.values())

    def logs_needed(self) -> List[str]:
        """Which log sections to ask for, given the registered keys."""
        logs: List[str] = []
        for key in self._by_key:
            if key in SPECIAL:
                continue
            log = _LOGS.get(key) or TYPE_LOGS.get(key) or "Events"
            if log not in logs:
                logs.append(log)
        return logs

    def for_entry(self, log: str, entry: dict) -> List[Callable[..., Any]]:
        """Handlers for one entry: the log's own handlers, then the entry type's."""
        fns = list(self._by_key.get(log.lower(), ()))
        entry_type = str(entry.get("Type") or ("Shot" if log == "Shots" else "")).lower()
        if entry_type and entry_type not in _LOGS and entry_type not in SPECIAL:
            # A type only counts for its own log (so a "Command" event can't be confused).
            if TYPE_LOGS.get(entry_type, "Events") == log:
                fns.extend(fn for fn in self._by_key.get(entry_type, ()) if fn not in fns)
        return fns


def ordered_entries(new: Dict[str, List[dict]]) -> List[Tuple[str, dict]]:
    """All new entries from every log, oldest first (by ``Seq``, shared across logs)."""
    items = [(log, entry) for log, entries in new.items() for entry in entries]
    items.sort(key=lambda item: (item[1].get("Seq") is None, item[1].get("Seq") or 0))
    return items
