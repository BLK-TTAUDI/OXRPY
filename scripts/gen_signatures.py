"""Generate oxrpy/_signatures.pyi: the typed method signatures for OxfordAPI and AsyncOxfordAPI.

The endpoint methods are written once (in oxrpy/_base.py and oxrpy/commands.py) and shared by
both clients, so at runtime they're typed as returning ``Any``. This script writes a stub that
tells editors and type checkers the real return types: ``List[Player]`` for the sync client and
a coroutine of it for the async one.

Run it after adding or changing an endpoint or command helper:

    python scripts/gen_signatures.py          # rewrite the stub
    python scripts/gen_signatures.py --check  # exit 1 if the stub is out of date (used by tests)
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from oxrpy._base import BaseClient  # noqa: E402
from oxrpy.commands import CommandHelpers  # noqa: E402

OUT = ROOT / "oxrpy" / "_signatures.pyi"

LOG_TYPES = {
    "get_killlogs": "t.KillLog", "get_modcalls": "t.ModCall", "get_radiocalls": "t.RadioCall",
    "get_joinlogs": "t.JoinLog", "get_events": "t.Event", "get_commandlogs": "t.CommandLog",
    "get_command_results": "t.CommandResultLog", "get_shots": "t.Shot",
}

RETURNS = {
    "get_server_data": "Optional[ServerData]",
    "get_server": "ServerData",
    "is_online": "bool",
    "get_players": "Optional[List[t.Player]]",
    "get_tracks": "Optional[t.Tracks]",
    "get_vehicles": "Optional[List[t.Vehicle]]",
    "get_world": "Optional[t.World]",
    "get_teams": "Optional[t.Teams]",
    "get_queue": "Optional[List[t.QueueEntry]]",
    "get_robberies": "Optional[List[t.Robbery]]",
    "get_atms": "Optional[List[t.Atm]]",
    "get_incidents": "Optional[t.Incidents]",
    "get_staff": "Optional[t.Staff]",
    "get_groups": "Optional[List[t.Group]]",
    "get_bans": "Optional[t.BansPage]",
    "get_settings": "Optional[t.Settings]",
    "get_catalogue": "Optional[t.Catalogue]",
    "get_audit": "Optional[t.AuditPage]",
    "run_command": "t.CommandResult",
    "run_commands": "List[t.CommandResult]",
    "execute_command": "t.CommandResult",
    "get_command": "t.CommandStatus",
    "get_status": "t.ApiStatus",
    "plan_staff_sync": "List[str]",
    "plan_group_sync": "List[str]",
    "find_player": "Optional[t.Player]",
    "players_on_team": "List[t.Player]",
    "staff_online": "List[t.Player]",
    "find_vehicle": "Optional[t.Vehicle]",
    **{name: f"List[{kind}]" for name, kind in LOG_TYPES.items()},
}

# Not endpoints: registration, cache control, and the 1.x manager properties.
SKIP = {"on", "on_request", "clear_catalogue_cache", "servers", "logs", "commands"}



def endpoint_methods():
    names = []
    for cls in (BaseClient, CommandHelpers):
        for name, value in vars(cls).items():
            if name.startswith("_") or name in SKIP or not callable(value) or name in names:
                continue
            names.append(name)
    return sorted(names)


def return_type(name: str) -> str:
    if name in RETURNS:
        return RETURNS[name]
    if hasattr(CommandHelpers, name):
        return "t.CommandResult"
    raise SystemExit(f"No return type for {name!r}: add it to RETURNS in {Path(__file__).name}")


def params(name: str) -> str:
    fn = getattr(BaseClient, name)
    parts = []
    seen_star = False
    for p in inspect.signature(fn).parameters.values():
        if p.name == "self":
            parts.append("self")
            continue
        text = p.name
        if p.kind is p.VAR_POSITIONAL:
            text = "*" + p.name
            seen_star = True
        elif p.kind is p.VAR_KEYWORD:
            text = "**" + p.name
        elif p.kind is p.KEYWORD_ONLY and not seen_star:
            parts.append("*")
            seen_star = True
        if p.annotation is not p.empty:
            text += f": {p.annotation if isinstance(p.annotation, str) else inspect.formatannotation(p.annotation)}"
        if p.default is not p.empty:
            text += f" = {p.default!r}" if p.default is None or isinstance(p.default, (bool, int, float, str)) else " = ..."
        parts.append(text)
    return ", ".join(parts)


def doc_body(name: str, indent: str = "        ") -> str:
    """The method's docstring, so editors and the docs site show it with the typed signature."""
    doc = inspect.getdoc(getattr(BaseClient, name))
    if not doc:
        return " ..."
    doc = doc.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    lines = doc.splitlines()
    if len(lines) == 1:
        return f'\n{indent}"""{lines[0]}"""'
    body = "\n".join((indent + line) if line.strip() else "" for line in lines)
    return f'\n{indent}"""{body.lstrip()}\n{indent}"""'


# What each on(...) key hands its handler, so type checkers can check handlers.
HANDLER_TYPES = [
    (("Kill", "KillLogs"), "t.KillLog"),
    (("ModCall", "ModCalls"), "t.ModCall"),
    (("RadioCall", "RadioCalls"), "t.RadioCall"),
    (("Join", "Leave", "JoinLogs"), "t.JoinLog"),
    (("Command", "CommandLogs"), "t.CommandLog"),
    (("CommandResult", "CommandResults"), "t.CommandResultLog"),
    (("Shot", "Shots"), "t.Shot"),
    (("poll", "ServerOnline", "ServerOffline", "ServerRestart"), "ServerData"),
    (("error",), "OxfordAPIError"),
]


def on_overloads() -> list:
    """Overloads for on(): one key and a decorator, or one key and the handler. Anything else
    (game event types like "SpeedCamera", several keys) is typed as a game Event / Any."""
    out = []
    for keys, kind in HANDLER_TYPES:
        literal = ", ".join(f'"{k}"' for k in keys)
        out += [
            "    @overload",
            # Narrower than the str overload below on purpose: specific keys win.
            f"    def on(self, key: Literal[{literal}], /) -> Callable[[Callable[[{kind}], Any]], Callable[[{kind}], Any]]: ...  # type: ignore[overload-overlap]",
            "    @overload",
            f"    def on(self, key: Literal[{literal}], handler: Callable[[{kind}], Any], /) -> Callable[[{kind}], Any]: ...",
        ]
    out += [
        "    @overload",
        "    def on(self, key: str, /) -> Callable[[Callable[[t.Event], Any]], Callable[[t.Event], Any]]: ...",
        "    @overload",
        "    def on(self, *keys: Any) -> Any:",
        '        """Register a handler for ``run_forever``. ``@api.on("Kill")`` handlers get a',
        "        ``KillLog``, ``\"Join\"``/``\"Leave\"`` a ``JoinLog``, ``\"poll\"`` and the server events the",
        "        response, ``\"error\"`` the exception, and game event types (``\"SpeedCamera\"``) an",
        '        ``Event``. See ``BaseClient.on``."""',
    ]
    return out


def render() -> str:
    names = endpoint_methods()
    lines = [
        "# Generated by scripts/gen_signatures.py. Don't edit by hand: run the script.",
        "#",
        "# Typed signatures for the methods both clients share. At runtime these classes are",
        "# empty (see _signatures.py); only editors and type checkers read this file.",
        "",
        "from datetime import timedelta",
        "from typing import Any, Callable, Iterable, List, Literal, Mapping, Optional, Sequence, Union, overload",
        "",
        "from . import types as t",
        "from ._base import ServerData",
        "from .commands import Target",
        "from .errors import OxfordAPIError",
        "",
        "",
        "class SyncSignatures:",
    ]
    lines += on_overloads()
    for name in names:
        lines.append(f"    def {name}({params(name)}) -> {return_type(name)}:{doc_body(name)}")
    lines += ["", "", "class AsyncSignatures:"]
    lines += on_overloads()
    for name in names:
        lines.append(f"    async def {name}({params(name)}) -> {return_type(name)}:{doc_body(name)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print(f"{OUT.name} is out of date: run python scripts/gen_signatures.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
