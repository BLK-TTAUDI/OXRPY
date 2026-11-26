"""Handler registry for ``api.on(...)`` and ``api.run_forever()``."""

from __future__ import annotations

import logging

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

#: Server state changes, worked out by comparing one poll with the last.
STATE_EVENTS = ("ServerOnline", "ServerOffline", "ServerRestart")

#: Special keys that aren't entries.
SPECIAL = ("poll", "error") + tuple(name.lower() for name in STATE_EVENTS)


class ServerWatcher:
    """Spots the server coming online, going offline or restarting between polls.

    ``ServerRestart`` fires when ``Server.StartedAt`` (or ``JobId``) changes, which means live
    data started over. A restart usually also gives ``ServerOffline`` then ``ServerOnline``,
    unless it happened between two polls.
    """

    def __init__(self) -> None:
        self.online: Any = None
        self.instance: Any = None

    def update(self, data: Dict[str, Any]) -> List[str]:
        """Record this poll and return the state events it causes (none on the first poll)."""
        online = bool(data.get("Online"))
        server = data.get("Server") or {}
        instance = server.get("StartedAt") or server.get("JobId")
        first = self.online is None
        events: List[str] = []
        if not first:
            if online and not self.online:
                events.append("ServerOnline")
            elif not online and self.online:
                events.append("ServerOffline")
            if online and instance is not None and self.instance is not None and instance != self.instance:
                events.append("ServerRestart")
        self.online = online
        if instance is not None:
            self.instance = instance
        return events


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


def dispatch_plan(
    handlers: Handlers,
    watcher: ServerWatcher,
    data: Dict[str, Any],
    new: Dict[str, List[dict]],
    skip_entries: bool,
) -> List[Tuple[Callable[..., Any], Any]]:
    """Every ``(handler, argument)`` call one poll should make, in order: state changes,
    then entries oldest first, then ``poll`` handlers."""
    calls: List[Tuple[Callable[..., Any], Any]] = []
    for name in watcher.update(data):
        calls.extend((fn, data) for fn in handlers.get(name))
    if not skip_entries:
        for log, entry in ordered_entries(new):
            calls.extend((fn, entry) for fn in handlers.for_entry(log, entry))
    calls.extend((fn, data) for fn in handlers.get("poll"))
    return calls


def ordered_entries(new: Dict[str, List[dict]]) -> List[Tuple[str, dict]]:
    """All new entries from every log, oldest first (by ``Seq``, shared across logs)."""
    items = [(log, entry) for log, entries in new.items() for entry in entries]
    items.sort(key=lambda item: (item[1].get("Seq") is None, item[1].get("Seq") or 0))
    return items


#: A handler that takes longer than this (seconds) gets a warning in the log.
SLOW_HANDLER_SECONDS = 5.0


def warn_if_slow(fn: Any, seconds: float) -> None:
    """Log a warning for a slow handler. Handlers run one at a time, in the order things happened,
    and the next poll waits for them, so a slow one leaves the bot behind without any error."""
    if seconds >= SLOW_HANDLER_SECONDS:
        logging.getLogger("oxrpy").warning(
            "Handler %s took %.1fs. The next poll waits for handlers, so events are arriving that "
            "much later. Hand slow work (a database write, a big upload) off to run separately: "
            "https://oxrpy.org/guide/events/#slow-handlers",
            getattr(fn, "__name__", repr(fn)), seconds,
        )
