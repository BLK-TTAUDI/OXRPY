# oxrpy

A Python wrapper for the Oxford RP API.

## Installation

Install from PyPI:
```
pip install oxrpy
```

Or from source:
```
pip install -r requirements.txt
```

## Usage

```python
from oxrpy import OxfordAPI

# Initialize with your server ID and key
api = OxfordAPI(server_id="your_server_id", server_key="your_server_key")

# Get server information
server_info = api.get_server()
print(server_info)

# Get current players
players = api.get_players()
print(players)

# Get queue
queue = api.get_queue()
print(queue)

# Get bans
bans = api.get_bans()
print(bans)
```

## API Endpoints

- `get_server()`: Returns general server information.
- `get_players()`: Returns list of current players.
- `get_queue()`: Returns the reserved server queue.
- `get_bans()`: Returns active bans.

All methods return the JSON response from the API.