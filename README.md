# oxrpy

A Python wrapper for the Oxford RP API.

## Installation

Install from PyPI:
```
pip install oxrpy
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

# Get kill logs
killlogs = api.get_killlogs()
print(killlogs)

# Execute a command
result = api.execute_command("announce Hello from API!")
print(result)
```

## API Endpoints

- `get_server()`: Returns general server information.
- `get_players()`: Returns list of current players.
- `get_queue()`: Returns the reserved server queue.
- `get_bans()`: Returns active bans.
- `get_killlogs()`: Returns recent kill logs (max 100 entries).
- `get_commandlogs()`: Returns recent command execution logs.
- `get_modcalls()`: Returns recent moderator call requests.
- `get_vehicles()`: Returns vehicles currently spawned.
- `execute_command(command)`: Executes a permitted command (e.g., "announce Hello!").

All methods return the JSON response from the API.
