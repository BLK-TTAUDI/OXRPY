"""Helpers that build and check command text, so ``api.ban("user", "RDM", "7d")`` sends
``ban user RDM 7d``.

Every helper checks its arguments before anything is sent (a bad duration or team raises
``ValueError`` straight away) and, by default, raises :class:`~oxrpy.CommandFailedError` if the
server says the command didn't work. Pass ``check=False`` to get the result back instead.

With :class:`~oxrpy.AsyncOxfordAPI` every helper returns a coroutine: ``await api.kick(...)``.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from typing import Any, Iterable, Optional, Union

TEAMS = ("Civilian", "Police", "Ambulance", "Highways", "Fire")
EMERGENCY_TEAMS = ("Police", "Ambulance", "Fire", "Highways")
WEATHER = ("Clear", "Rain", "Snow", "Thunderstorm")
TOOLS = ("megaphone", "firestarter", "lectern", "flag", "staffcuffs")
ALERT_STYLES = {"normal": "alert", "yellow": "yellowalert", "red": "redalert"}

_DURATION = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?$", re.IGNORECASE)
_MAX_BAN_MINUTES = 3653 * 24 * 60  # "up to 10 years"; the server has the final say

Target = Union[str, int]


def _target(value: Target, what: str = "player") -> str:
    """A single name, user ID or keyword like ``all`` / ``team:Police``: no spaces."""
    text = str(value).strip()
    if text.startswith("@"):
        text = text[1:]
    if not text or any(ch.isspace() for ch in text):
        raise ValueError(f"{what} must be one username, display name or user ID, got {value!r}")
    return text


def _text(value: Any, what: str, max_len: Optional[int] = None) -> str:
    """Free text: the rest of the line. Newlines and runs of spaces become one space."""
    text = " ".join(str(value).split())
    if not text:
        raise ValueError(f"{what} can't be empty")
    if max_len is not None and len(text) > max_len:
        raise ValueError(f"{what} is {len(text)} characters; the most is {max_len}")
    return text


def _choice(value: str, options: Iterable[str], what: str) -> str:
    options = tuple(options)
    for option in options:
        if str(value).strip().lower() == option.lower():
            return option
    raise ValueError(f"{what} must be one of {', '.join(options)}, got {value!r}")


def _int_range(value: Any, low: int, high: int, what: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a whole number, got {value!r}") from None
    if number != value and not isinstance(value, str):
        raise ValueError(f"{what} must be a whole number, got {value!r}")
    if not low <= number <= high:
        raise ValueError(f"{what} must be from {low} to {high}, got {number}")
    return number


def _number(value: Any, what: str) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number, got {value!r}") from None


def format_duration(duration: Union[str, int, timedelta, None]) -> str:
    """Turn ``"7d"``, ``"1d12h"``, ``timedelta(hours=12)`` or a number of seconds into the
    ``ban`` command's duration. ``None`` or ``"permanent"`` gives ``"permanent"``."""
    if duration is None:
        return "permanent"
    if isinstance(duration, timedelta):
        minutes = int(duration.total_seconds() // 60)
    elif isinstance(duration, (int, float)) and not isinstance(duration, bool):
        minutes = int(duration // 60)
    else:
        text = str(duration).strip().lower().replace(" ", "")
        if text == "permanent":
            return "permanent"
        match = _DURATION.match(text)
        if not text or not match:
            raise ValueError(
                f"Ban duration must look like 30m, 12h, 7d or 1d12h (or 'permanent'), got {duration!r}"
            )
        days, hours, mins = (int(g) if g else 0 for g in match.groups())
        minutes = days * 1440 + hours * 60 + mins
        if 1 <= minutes <= _MAX_BAN_MINUTES:
            return text
    if not 1 <= minutes <= _MAX_BAN_MINUTES:
        raise ValueError("Ban duration must be from 1 minute to 10 years")
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    return "".join(f"{n}{unit}" for n, unit in ((days, "d"), (hours, "h"), (mins, "m")) if n)


class CommandHelpers:
    """Mixed into the clients. Each method sends one command with :meth:`run_command`."""

    def run_command(self, command: str, *, check: bool = False) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _send(self, *parts: Any, check: bool) -> Any:
        return self.run_command(" ".join(str(p) for p in parts if p != ""), check=check)

    # Moderation ---------------------------------------------------------------

    def kick(self, player: Target, reason: Optional[str] = None, *, check: bool = True) -> Any:
        """Move someone out of your server, showing the reason. Staff can't be kicked."""
        return self._send("kick", _target(player), _text(reason, "reason") if reason else "", check=check)

    def ban(
        self,
        user: Target,
        reason: Optional[str] = None,
        duration: Union[str, int, timedelta, None] = None,
        *,
        check: bool = True,
    ) -> Any:
        """Ban someone, in the server or not. ``duration`` is ``"30m"``, ``"12h"``, ``"7d"``,
        ``"1d12h"``, a ``timedelta`` or seconds; leave it out for a permanent ban.
        Reasons can be up to 200 characters."""
        parts = ["ban", _target(user, "user")]
        if reason:
            parts.append(_text(reason, "reason", 200))
        if reason or duration is not None:
            # Always end with the duration, so a reason ending in a number isn't read as one.
            parts.append(format_duration(duration))
        return self._send(*parts, check=check)

    def unban(self, user: Target, *, check: bool = True) -> Any:
        """Lift someone's ban."""
        return self._send("unban", _target(user, "user"), check=check)

    def jail(self, player: Target, seconds: Optional[int] = None, *, check: bool = True) -> Any:
        """Jail someone as an arrest would, for 10 to 3,600 seconds (or the usual sentence)."""
        return self._send("jail", _target(player),
                          _int_range(seconds, 10, 3600, "seconds") if seconds is not None else "",
                          check=check)

    def release(self, player: Target, *, check: bool = True) -> Any:
        """Release someone from jail."""
        return self._send("release", _target(player), check=check)

    def wanted(self, players: Target, level: int, *, check: bool = True) -> Any:
        """Set a wanted level from 0 to 3. ``players`` can be a name, ``all``, ``team:Civilian``…"""
        return self._send("wanted", _target(players, "players"), _int_range(level, 0, 3, "level"), check=check)

    def pm(self, players: Target, message: str, *, check: bool = True) -> Any:
        """Send a private message, shown with your server's name and logo."""
        return self._send("pm", _target(players, "players"), _text(message, "message"), check=check)

    def resolve_modcall(self, case_id: Target, *, check: bool = True) -> Any:
        """Mark a mod call (help request) as handled. The ``CaseId`` is in ``ModCalls``."""
        return self._send("modcall", "resolve", _target(case_id, "case_id"), check=check)

    # Staff and groups ---------------------------------------------------------

    def rank(self, user: Target, rank: str, *, check: bool = True) -> Any:
        """Put someone on the staff with a rank (its name or Id, e.g. ``"Admin"``), or change it."""
        return self._send("rank", _target(user, "user"), _text(rank, "rank"), check=check)

    def unrank(self, user: Target, *, check: bool = True) -> Any:
        """Take someone off the staff, whatever their rank."""
        return self._send("unrank", _target(user, "user"), check=check)

    def group_add(self, user: Target, group: str, *, check: bool = True) -> Any:
        """Add someone to one of your groups (AdvancedServer)."""
        return self._send("group", "add", _target(user, "user"), _text(group, "group"), check=check)

    def group_remove(self, user: Target, group: str, *, check: bool = True) -> Any:
        """Take someone out of one of your groups (AdvancedServer)."""
        return self._send("group", "remove", _target(user, "user"), _text(group, "group"), check=check)

    # Players and vehicles -----------------------------------------------------

    def set_team(self, player: Target, team: str, *, check: bool = True) -> Any:
        """Put someone on a team, ignoring team limits and locks."""
        return self._send("team", _target(player), _choice(team, TEAMS, "team"), check=check)

    def respawn(self, players: Target, *, check: bool = True) -> Any:
        """Respawn them (the ``load`` command)."""
        return self._send("load", _target(players, "players"), check=check)

    def revive(self, players: Target, *, check: bool = True) -> Any:
        """Get anyone downed back up."""
        return self._send("revive", _target(players, "players"), check=check)

    def teleport(self, players: Target, to_player: Target, *, check: bool = True) -> Any:
        """Teleport them next to another player (the ``tp`` command)."""
        return self._send("tp", _target(players, "players"), _target(to_player, "to_player"), check=check)

    def teleport_to_vehicle(self, players: Target, owner: Target, *, check: bool = True) -> Any:
        """Teleport them next to another player's vehicle (the ``tocar`` command)."""
        return self._send("tocar", _target(players, "players"), _target(owner, "owner"), check=check)

    def set_invincible(self, players: Target, invincible: bool = True, *, check: bool = True) -> Any:
        """Make them unable to be hurt by weapons (or able to again), until they leave."""
        return self._send("invincible" if invincible else "uninvincible", _target(players, "players"), check=check)

    def give(self, players: Target, tool: str, *, check: bool = True) -> Any:
        """Give a RoleplayKit tool: megaphone, firestarter, lectern, flag or staffcuffs."""
        return self._send("give", _target(players, "players"), _choice(tool, TOOLS, "tool"), check=check)

    def despawn_vehicle(self, player: Target, *, check: bool = True) -> Any:
        """Put someone's vehicle away (the ``despawn`` command)."""
        return self._send("despawn", _target(player), check=check)

    def remove_vehicle(self, plate_or_player: Target, *, check: bool = True) -> Any:
        """Remove a vehicle by registration (``"RJ75 FLK"``) or by its owner."""
        target = str(plate_or_player).replace(" ", "")
        return self._send("removevehicle", _target(target, "plate_or_player"), check=check)

    def spawn_vehicle(self, player: Target, custom_vehicle_id: str, *, check: bool = True) -> Any:
        """Spawn one of your FleetKit custom vehicles in front of them."""
        return self._send("spawnvehicle", _target(player), _target(custom_vehicle_id, "custom_vehicle_id"),
                          check=check)

    def repair(self, player: Target, *, check: bool = True) -> Any:
        """Fully repair someone's vehicle, tyres included."""
        return self._send("repair", _target(player), check=check)

    def refuel(self, player: Target, *, check: bool = True) -> Any:
        """Fill someone's tank or battery."""
        return self._send("refuel", _target(player), check=check)

    # World and messages -------------------------------------------------------

    def set_time(self, hour: float, *, check: bool = True) -> Any:
        """Set the clock to an hour from 0 to 24 (``13.5`` is 13:30)."""
        try:
            value = float(hour)
        except (TypeError, ValueError):
            raise ValueError(f"hour must be a number, got {hour!r}") from None
        if not 0 <= value <= 24:
            raise ValueError(f"hour must be from 0 to 24, got {hour}")
        return self._send("time", f"{value:g}", check=check)

    def lock_time(self, locked: bool = True, *, check: bool = True) -> Any:
        """Stop the clock (or start it again with ``locked=False``)."""
        return self._send("locktime" if locked else "unlocktime", check=check)

    def set_weather(self, weather: str, *, check: bool = True) -> Any:
        """Clear, Rain, Snow or Thunderstorm."""
        return self._send("weather", _choice(weather, WEATHER, "weather").lower(), check=check)

    def lock_weather(self, locked: bool = True, *, check: bool = True) -> Any:
        """Stop the weather changing by itself (or let it again with ``locked=False``)."""
        return self._send("lockweather" if locked else "unlockweather", check=check)

    def announce(self, message: str, *, check: bool = True) -> Any:
        """An announcement to everyone."""
        return self._send("announce", _text(message, "message"), check=check)

    def team_announce(self, team: str, message: str, *, check: bool = True) -> Any:
        """An announcement to one team."""
        return self._send("teamannounce", _choice(team, TEAMS, "team"), _text(message, "message"), check=check)

    def alert(self, message: str, style: str = "normal", *, check: bool = True) -> Any:
        """An alert to everyone, ``style`` ``"normal"``, ``"yellow"`` or ``"red"``."""
        command = ALERT_STYLES[_choice(style, ALERT_STYLES, "style")]
        return self._send(command, _text(message, "message"), check=check)

    def set_message(self, message: str, *, check: bool = True) -> Any:
        """Pin a message on everyone's screen until it's removed."""
        return self._send("setmessage", _text(message, "message"), check=check)

    def remove_message(self, *, check: bool = True) -> Any:
        """Remove the pinned message."""
        return self._send("removemessage", check=check)

    def countdown(self, seconds: int, *, check: bool = True) -> Any:
        """Show everyone a countdown. ``0`` stops it."""
        return self._send("countdown", _int_range(seconds, 0, 10 ** 7, "seconds"), check=check)

    def speed_limit(self, mph: Optional[int], *, check: bool = True) -> Any:
        """Limit every vehicle to 5-200 MPH (RoleplayKit). ``None`` or ``0`` lifts it."""
        value = "off" if not mph else _int_range(mph, 5, 200, "mph")
        return self._send("speedlimit", value, check=check)

    # Control room and callouts ------------------------------------------------

    def create_incident(self, team: str, priority: int, x: float, z: float, text: str, *,
                        check: bool = True) -> Any:
        """Open a control-room incident at ``x, z`` (studs) for an emergency team, priority 1-3.
        The new incident's ID is in the result's ``Message``."""
        return self._send(
            "incident", "create", _choice(team, EMERGENCY_TEAMS, "team"),
            _int_range(priority, 1, 3, "priority"), _number(x, "x"), _number(z, "z"),
            _text(text, "text", 200), check=check,
        )

    def assign_incident(self, incident_id: str, player: Target, *, check: bool = True) -> Any:
        """Send a unit to an incident."""
        return self._send("incident", "assign", _target(incident_id, "incident_id"), _target(player), check=check)

    def close_incident(self, incident_id: str, *, check: bool = True) -> Any:
        """Close an incident."""
        return self._send("incident", "close", _target(incident_id, "incident_id"), check=check)

    def radio(self, team: str, message: str, *, check: bool = True) -> Any:
        """A radio message from Control to an emergency team."""
        return self._send("radio", _choice(team, EMERGENCY_TEAMS, "team"), _text(message, "message"), check=check)

    def start_callout(self, team: str, key: str, *, check: bool = True) -> Any:
        """Start a Fire or Highways callout by its key (RoleplayKit; ``list_callouts`` shows keys)."""
        return self._send("callout", _choice(team, ("Fire", "Highways"), "team"), _target(key, "key"), check=check)

    def ambulance_callout(self, player: Optional[Target] = None, *, check: bool = True) -> Any:
        """A patient callout for that paramedic, or the first one free (RoleplayKit)."""
        return self._send("callout", "ambulance", _target(player) if player is not None else "", check=check)

    def list_callouts(self, *, check: bool = True) -> Any:
        """The callouts you can start, with their keys, in the result's ``Message``."""
        return self._send("callouts", check=check)

    def stop_fires(self, *, check: bool = True) -> Any:
        """Put out every fire and end every fire callout (RoleplayKit)."""
        return self._send("stopfires", check=check)

    # Server -------------------------------------------------------------------

    def set_setting(self, name: str, value: Any, *, check: bool = True) -> Any:
        """Change a Server Management setting. ``value`` is sent as JSON, so pass Python values:
        ``api.set_setting("TeamLimits", {"Police": 8})``. Lists and objects replace the whole value."""
        return self._send("setting", _target(name, "name"), json.dumps(value, ensure_ascii=False), check=check)

    def new_join_code(self, *, check: bool = True) -> Any:
        """Replace the join code with a new random one. The new code is in ``Message``."""
        return self._send("joincode", check=check)

    def queue_remove(self, user: Target, *, check: bool = True) -> Any:
        """Take someone out of the join queue."""
        return self._send("queue", "remove", _target(user, "user"), check=check)

    def queue_front(self, user: Target, *, check: bool = True) -> Any:
        """Move someone to the front of the join queue."""
        return self._send("queue", "front", _target(user, "user"), check=check)

    def clear_placeables(self, player: Target = "all", *, check: bool = True) -> Any:
        """Pick up one person's cones, signs and other placed items, or everyone's."""
        return self._send("clearplaceables", _target(player), check=check)

    def shutdown(self, *, check: bool = True) -> Any:
        """Shut the server down, sending everyone to a public server."""
        return self._send("shutdown", check=check)
