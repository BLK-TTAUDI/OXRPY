"""Finding players and vehicles in the API's data, the same way Oxford's commands do.

These work on any list you already have (``api.latest.players``, a ``Players`` section…). The
clients' ``find_player``, ``players_on_team``, ``staff_online`` and ``find_vehicle`` methods use
them with ``api.latest`` when it's fresh, and fetch otherwise.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Union

from . import types as t


class AmbiguousMatchError(LookupError):
    """More than one player matched a name. ``matches`` holds them."""

    def __init__(self, query: str, matches: Sequence[t.Player]) -> None:
        names = ", ".join(str(p.get("Username")) for p in matches[:5])
        more = f" and {len(matches) - 5} more" if len(matches) > 5 else ""
        super().__init__(f"{query!r} matches {len(matches)} players ({names}{more}); name one")
        self.query = query
        self.matches = list(matches)


def _names(player: t.Player) -> List[str]:
    return [str(player.get(k) or "").lower() for k in ("Username", "DisplayName")]


def find_players(players: Optional[Iterable[t.Player]], query: Union[str, int]) -> List[t.Player]:
    """Everyone ``query`` could mean, using Oxford's ``<player>`` rules, best matches first:

    1. a username or display name (any case),
    2. then a user ID,
    3. then part of a username or display name.

    Returns ``[]`` for no match (or when ``players`` is ``None``, e.g. the server's offline).
    """
    people = list(players or [])
    text = str(query).strip()
    if text.startswith("@"):
        text = text[1:]
    if not text:
        return []
    lower = text.lower()

    by_username = [p for p in people if str(p.get("Username") or "").lower() == lower]
    if by_username:
        return by_username
    by_display = [p for p in people if str(p.get("DisplayName") or "").lower() == lower]
    if by_display:
        return by_display
    if text.isdigit():
        by_id = [p for p in people if str(p.get("UserId")) == text]
        if by_id:
            return by_id
    return [p for p in people if any(lower in name for name in _names(p))]


def find_player(players: Optional[Iterable[t.Player]], query: Union[str, int]) -> Optional[t.Player]:
    """The one player ``query`` means (see :func:`find_players`), or ``None`` if nobody matches.

    Raises:
        AmbiguousMatchError: Several players match; its ``matches`` lists them.
    """
    matches = find_players(players, query)
    if len(matches) > 1:
        raise AmbiguousMatchError(str(query), matches)
    return matches[0] if matches else None


def players_on_team(players: Optional[Iterable[t.Player]], team: str) -> List[t.Player]:
    """Everyone on a team (any case: ``"police"`` works)."""
    wanted = team.strip().lower()
    return [p for p in players or [] if str(p.get("Team") or "").lower() == wanted]


def staff_online(players: Optional[Iterable[t.Player]]) -> List[t.Player]:
    """Players in the server who have a staff rank (the owner included)."""
    return [p for p in players or [] if p.get("Rank")]


def _plate(text: object) -> str:
    return "".join(str(text).split()).upper()


def find_vehicle(
    vehicles: Optional[Iterable[t.Vehicle]],
    plate_or_player: Union[str, int],
    players: Optional[Iterable[t.Player]] = None,
) -> Optional[t.Vehicle]:
    """A vehicle by registration (spaces and case don't matter: ``"rj75flk"`` finds
    ``"RJ75 FLK"``), or else by its owner: a user ID, or a name looked up in ``players``.

    Raises:
        AmbiguousMatchError: The name matches several players.
    """
    cars = list(vehicles or [])
    wanted = _plate(plate_or_player)
    for car in cars:
        if _plate(car.get("Plate") or "") == wanted:
            return car
    owner_id: Optional[int] = None
    text = str(plate_or_player).strip().lstrip("@")
    if text.isdigit():
        owner_id = int(text)
    if players is not None:
        owner = find_player(players, plate_or_player)
        if owner is not None:
            owner_id = owner.get("UserId")
    if owner_id is None:
        return None
    return next((car for car in cars if car.get("OwnerId") == owner_id), None)
