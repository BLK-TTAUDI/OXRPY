"""Remembering where a follower got to, so a restarted bot carries on where it left off.

Pass ``save_to=`` to ``run_forever()`` or ``follow()``:

* a file path (``"cursor.json"``), which oxrpy reads at start and rewrites after each poll, or
* your own object with ``load() -> dict | None`` and ``save(state: dict)`` methods, to keep it
  in a database, Redis, or wherever your bot keeps things.

The position is saved *after* your handlers have run for a poll. If your bot crashes part-way
through, the entries from that poll come again on restart, so nothing is lost. A handler may
very occasionally see an entry twice; use the entry's ``Id`` if that matters.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable

logger = logging.getLogger("oxrpy")

STATE_VERSION = 1


@runtime_checkable
class StateStore(Protocol):
    """Anything with these two methods can hold a follower's position."""

    def load(self) -> Optional[Dict[str, Any]]: ...

    def save(self, state: Dict[str, Any]) -> None: ...


class FileState:
    """Keeps the position in a small JSON file. Writes are atomic: a crash mid-write never
    leaves a half-written file."""

    def __init__(self, path: Union[str, "os.PathLike[str]"]) -> None:
        self.path = Path(path)

    def load(self) -> Optional[Dict[str, Any]]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        try:
            state = json.loads(text)
        except ValueError:
            logger.warning("Ignoring %s: it isn't valid JSON, so starting from the newest entries", self.path)
            return None
        return state if isinstance(state, dict) else None

    def save(self, state: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def __repr__(self) -> str:
        return f"FileState({str(self.path)!r})"


def as_store(save_to: Any) -> Optional[StateStore]:
    """Turn a ``save_to=`` argument into a store."""
    if save_to is None:
        return None
    if isinstance(save_to, (str, os.PathLike)):
        return FileState(save_to)
    if isinstance(save_to, StateStore):
        return save_to
    raise TypeError("save_to must be a file path or an object with load() and save(state) methods")


def make_state(cursor: Optional[int], handled: Dict[str, int]) -> Dict[str, Any]:
    return {"Version": STATE_VERSION, "Cursor": cursor, "Handled": dict(handled), "SavedAt": int(time.time())}


def read_state(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Check a loaded state; returns ``{"Cursor", "Handled"}`` or ``None`` if it's unusable."""
    if not state or state.get("Cursor") is None:
        return None
    try:
        cursor = int(state["Cursor"])
        handled = {str(k): int(v) for k, v in (state.get("Handled") or {}).items()}
    except (TypeError, ValueError):
        logger.warning("Ignoring saved position: it isn't in the expected format")
        return None
    return {"Cursor": cursor, "Handled": handled}
