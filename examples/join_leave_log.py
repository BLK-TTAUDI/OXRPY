"""Print who joins and leaves, and every kill, as it happens.

Run it:
    pip install oxrpy
    set OXFD_SERVER_KEY=your-key        (PowerShell: $env:OXFD_SERVER_KEY = "your-key")
    python join_leave_log.py
"""

import os
from datetime import datetime

from oxrpy import OxfordAPI

api = OxfordAPI(os.environ["OXFD_SERVER_KEY"])


def stamp(entry):
    return datetime.fromtimestamp(entry["At"]).strftime("%H:%M:%S")


@api.on("Join")
def on_join(entry):
    print(f"{stamp(entry)}  + {entry['Username']} joined")


@api.on("Leave")
def on_leave(entry):
    print(f"{stamp(entry)}  - {entry['Username']} left")


@api.on("Kill")
def on_kill(kill):
    weapon = kill.get("Weapon") or "unknown weapon"
    print(f"{stamp(kill)}  x {kill['KillerUsername']} downed {kill['VictimUsername']} with {weapon}")


@api.on("ServerOffline")
def on_offline(data):
    print("The server went offline")


@api.on("ServerOnline")
def on_online(data):
    print("The server is back online")


print("Watching the server. Press Ctrl+C to stop.")
try:
    api.run_forever()
except KeyboardInterrupt:
    pass
