"""Keep staff ranks and groups in step with somewhere else (Discord roles, a database…).

Oxford's advice is to compare what the server has with what you want and send only the
differences. These functions work out those differences as commands. The clients'
``plan_staff_sync``/``sync_staff`` and ``plan_group_sync``/``sync_group`` fetch the current
lists for you and run the commands within the game's limits.

Users are identified by user ID only: a username can match nobody, or someone else after a
name change.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Set, Union

UserKey = Union[int, str]

#: The game runs at most 15 commands every 10 seconds per server.
GAME_COMMANDS_PER_WINDOW = 15
GAME_WINDOW_SECONDS = 10.0


def _user_id(value: UserKey) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Not a user ID: {value!r}")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    raise ValueError(
        f"Sync needs Roblox user IDs, not names (a name can change or match someone else): {value!r}"
    )


def _find_rank(ranks: List[dict], wanted: str) -> str:
    target = str(wanted).strip().lower()
    for rank in ranks:
        if target in (str(rank.get("Id", "")).lower(), str(rank.get("Name", "")).lower()):
            return str(rank["Id"])
    names = ", ".join(str(r.get("Name")) for r in ranks) or "none"
    raise ValueError(f"No rank called {wanted!r} on this server (ranks: {names})")


def plan_staff_changes(
    staff: Mapping[str, Any],
    desired: Mapping[UserKey, Optional[str]],
    *,
    remove_others: bool = False,
) -> List[str]:
    """The ``rank``/``unrank`` commands that turn the current staff list into ``desired``.

    Args:
        staff: The ``Staff`` section (``{ OwnerId, Staff, Ranks }``).
        desired: User ID -> rank name or Id (``None`` to take them off the staff).
        remove_others: Also unrank staff who aren't in ``desired``. Off by default, so staff
            you added by hand are left alone.

    The owner is never touched. Ranks are matched by name or Id, ignoring case.
    """
    owner = staff.get("OwnerId")
    ranks = list(staff.get("Ranks") or [])
    current: Dict[int, str] = {}
    for member in staff.get("Staff") or []:
        current[int(member["UserId"])] = str(member.get("RankId") or "").lower()

    wanted: Dict[int, Optional[str]] = {}
    for key, rank in desired.items():
        user_id = _user_id(key)
        if user_id == owner:
            continue
        wanted[user_id] = _find_rank(ranks, rank) if rank is not None else None

    removals: List[str] = []
    changes: List[str] = []
    for user_id in sorted(wanted):
        rank_id = wanted[user_id]
        if rank_id is None:
            if user_id in current:
                removals.append(f"unrank {user_id}")
        elif current.get(user_id) != rank_id.lower():
            changes.append(f"rank {user_id} {rank_id}")
    if remove_others:
        for user_id in sorted(current):
            if user_id not in wanted and user_id != owner:
                removals.append(f"unrank {user_id}")
    return removals + changes


def plan_group_changes(
    groups: Iterable[Mapping[str, Any]],
    group: str,
    members: Iterable[UserKey],
    *,
    remove_others: bool = True,
) -> List[str]:
    """The ``group add``/``group remove`` commands that make ``group`` contain ``members``.

    Args:
        groups: The ``Groups`` section.
        group: The group's name or Id (ignoring case).
        members: User IDs who should be in it.
        remove_others: Take out anyone not in ``members`` (default). Set ``False`` to only add.
    """
    target = str(group).strip().lower()
    groups = list(groups)
    found = next(
        (g for g in groups if target in (str(g.get("Id", "")).lower(), str(g.get("Name", "")).lower())),
        None,
    )
    if found is None:
        names = ", ".join(str(g.get("Name")) for g in groups) or "none (groups need AdvancedServer)"
        raise ValueError(f"No group called {group!r} on this server (groups: {names})")
    group_id = found["Id"]
    current: Set[int] = {int(m) for m in found.get("Members") or []}
    wanted: Set[int] = {_user_id(m) for m in members}
    commands = [f"group add {user_id} {group_id}" for user_id in sorted(wanted - current)]
    if remove_others:
        commands += [f"group remove {user_id} {group_id}" for user_id in sorted(current - wanted)]
    return commands


class CommandWindow:
    """Tracks commands sent in the last 10 seconds, to stay under the game's 15."""

    def __init__(self, limit: int = GAME_COMMANDS_PER_WINDOW, window: float = GAME_WINDOW_SECONDS) -> None:
        self.limit = limit
        self.window = window
        self._sent: Deque[float] = deque()

    def wait_time(self, count: int, now: Optional[float] = None) -> float:
        """Seconds to wait before ``count`` more commands fit."""
        now = time.monotonic() if now is None else now
        while self._sent and self._sent[0] <= now - self.window:
            self._sent.popleft()
        over = len(self._sent) + count - self.limit
        if over <= 0:
            return 0.0
        return max(0.0, self._sent[over - 1] + self.window - now + 0.25)

    def record(self, count: int, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        self._sent.extend([now] * count)


def chunk(commands: List[str], size: int) -> List[List[str]]:
    return [commands[i:i + size] for i in range(0, len(commands), size)]
