"""A small command-line tool: ``oxrpy status``, ``oxrpy server``, ``oxrpy players``.

Commands that read your server need your key in the ``OXFD_SERVER_KEY`` environment variable
(or ``--key``, though that can end up in your shell history).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from . import __version__
from .client import OxfordAPI
from .errors import OxfordAPIError


def _api(args: argparse.Namespace) -> OxfordAPI:
    key = args.key or os.environ.get("OXFD_SERVER_KEY")
    if not key:
        raise SystemExit("Set OXFD_SERVER_KEY to your server's API key (or pass --key).")
    return OxfordAPI(key)


def _ago(seconds: Optional[float]) -> str:
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = [f"{days}d" if days else "", f"{hours}h" if hours else "", f"{minutes}m"]
    return " ".join(p for p in parts if p)


def cmd_status(args: argparse.Namespace) -> int:
    status = OxfordAPI("unused", rate_limit="none").get_status()
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    last_hour = status.get("LastHour") or {}
    windows = (status.get("Uptime") or {}).get("Windows") or {}
    print(f"Oxford API: {status.get('Status', 'unknown')}")
    print(f"Running for: {_ago(status.get('UptimeSeconds'))}")
    if last_hour:
        print(f"Response time (last hour): {last_hour.get('P50Ms')} ms median, {last_hour.get('P95Ms')} ms 95th")
    if windows:
        print("Uptime: " + ", ".join(f"{k} {v}%" for k, v in windows.items()))
    return 0


def cmd_server(args: argparse.Namespace) -> int:
    data = _api(args).get_server()
    if args.json:
        print(json.dumps(data, indent=2))
        return 0
    server = data.get("Server") or {}
    print(server.get("Name") or "Unknown server")
    print(f"  {'Online' if data.online else 'Offline'}, "
          f"{server.get('CurrentPlayers', 0)}/{server.get('MaxPlayers', '?')} players")
    print(f"  Join code: {server.get('JoinCode') or '-'}   Access: {server.get('Access') or '-'}")
    print(f"  Packages: {', '.join(server.get('Packages') or []) or 'none'}")
    if data.online and server.get("Uptime") is not None:
        print(f"  Up for: {_ago(server.get('Uptime'))}")
    return 0


def cmd_players(args: argparse.Namespace) -> int:
    players = _api(args).get_players()
    if args.json:
        print(json.dumps(players, indent=2))
        return 0
    if players is None:
        print("The server is offline.")
        return 0
    if not players:
        print("Nobody's in the server.")
        return 0
    rows = sorted(players, key=lambda p: (str(p.get("Team") or ""), str(p.get("Username") or "").lower()))
    width = max(len(str(p.get("Username") or "")) for p in rows)
    for p in rows:
        where = (p.get("Location") or {}).get("Area") or ""
        rank = f" [{p['Rank']}]" if p.get("Rank") else ""
        print(f"{str(p.get('Username') or ''):<{width}}  {str(p.get('Team') or '-'):<10} {where}{rank}")
    print(f"\n{len(rows)} player{'s' if len(rows) != 1 else ''}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="oxrpy", description="Oxford Response API from the command line.")
    parser.add_argument("--version", action="version", version=f"oxrpy {__version__}")
    parser.add_argument("--key", help="server API key (defaults to the OXFD_SERVER_KEY environment variable)")
    parser.add_argument("--json", action="store_true", help="print the raw JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="is the Oxford API up? (no key needed)").set_defaults(fn=cmd_status)
    sub.add_parser("server", help="your server's name, players, join code and packages").set_defaults(fn=cmd_server)
    sub.add_parser("players", help="who's in your server").set_defaults(fn=cmd_players)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except OxfordAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
