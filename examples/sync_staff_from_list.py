"""Keep your in-game staff ranks matching a list, sending only the changes.

In a real bot the list would come from Discord roles or a database. Here it's a dictionary of
Roblox user IDs to rank names (use user IDs, not usernames: names change).

Run it:
    pip install oxrpy
    set OXFD_SERVER_KEY=your-key
    python sync_staff_from_list.py            (shows what it would do)
    python sync_staff_from_list.py --apply    (does it)
"""

import os
import sys

from oxrpy import OxfordAPI

STAFF = {
    81234401: "Mod",
    81239912: "Senior Moderator",
    99120501: "Admin",
    77001200: None,      # None takes someone off the staff
}

api = OxfordAPI(os.environ["OXFD_SERVER_KEY"])

# remove_others=True would also unrank anyone on the staff who isn't in STAFF.
commands = api.plan_staff_sync(STAFF, remove_others=False)

if not commands:
    print("Staff already match. Nothing to do.")
elif "--apply" not in sys.argv:
    print("These commands would be sent (run with --apply to send them):")
    for command in commands:
        print("  " + command)
else:
    for command, result in api.sync_staff(STAFF, remove_others=False):
        print(f"{result['Status']:<10} {command}  ({result.get('Message')})")
