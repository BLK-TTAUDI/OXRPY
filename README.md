# oxrpy

A Python wrapper for the [Oxford Response private server API](https://docs.oxfd.re/). Use it to
read what's happening on your server and run commands on it from your own bot, website or tool.

**Full documentation: [oxrpy.org](https://oxrpy.org)**

```
pip install oxrpy
```

For async code, like a discord.py bot, install `"oxrpy[async]"` instead. You'll need Python 3.10
or newer.

## Quick look

```python
import os
from oxrpy import OxfordAPI

api = OxfordAPI(os.environ["OXFD_SERVER_KEY"])

for player in api.get_players() or []:
    print(player["Username"], player["Team"])

@api.on("Kill")
def on_kill(kill):
    print(kill["KillerUsername"], "downed", kill["VictimUsername"])

api.announce("Server restart in 5 minutes")
api.run_forever()
```

You'll need your server's API key, from **Server Management > External > API Key**, and the
server needs the **API package**. Keep the key private: anyone with it can run commands on your
server.

## Documentation

Everything is on **[oxrpy.org](https://oxrpy.org)**:

- [Getting started](https://oxrpy.org/python/)
- [Reading data](https://oxrpy.org/guide/reading-data/): players, vehicles, bans, settings and more
- [Events and logs](https://oxrpy.org/guide/events/): react to kills, joins and other events
- [Commands](https://oxrpy.org/guide/commands/): kick, ban, announce, change settings
- [Async and Discord bots](https://oxrpy.org/guide/async/)
- [Many servers and app keys](https://oxrpy.org/guide/many-servers/): for bots lots of servers use
- [Maps and positions](https://oxrpy.org/guide/map/)
- [Rate limits and errors](https://oxrpy.org/guide/limits-and-errors/)
- [Command line](https://oxrpy.org/guide/cli/) and [examples](https://oxrpy.org/examples/)
- [Cookbook](https://oxrpy.org/cookbook/): complete recipes, like a Discord kill feed
- [API reference](https://oxrpy.org/reference/client/)

Using JavaScript? There's [oxrpy for JavaScript and TypeScript](https://github.com/BLK-TTAUDI/oxrpy-js)
with the same features.

> **Upgrading from 1.x?** Oxford is switching off the old endpoints on **1 January 2027**.
> Version 2 uses the new API, so it'll keep working after that. The data comes back in a
> different format, though, so check [the changelog](https://github.com/BLK-TTAUDI/OXRPY/blob/main/CHANGELOG.md)
> before you upgrade.

## Support

oxrpy is free to use. If it's saved you some time, you can
[buy me a coffee](https://buymeacoffee.com/blk_ttaudi) to help keep it going.

## License

Proprietary. See the [LICENSE](https://github.com/BLK-TTAUDI/OXRPY/blob/main/LICENSE) file.
