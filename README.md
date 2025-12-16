# oxrpy
A Python wrapper for the Oxford Response API.

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

# Use all methods directly
server_info = api.get_server()
players = api.get_players()

# Or use grouped managers via properties
servers = api.servers
server_info = servers.get_server()
players = servers.get_players()
bans = servers.get_bans()

logs = api.logs
kill_logs = logs.get_killlogs()
mod_calls = logs.get_modcalls()

commands = api.commands
result = commands.execute_command("announce Hello!")
```

You can also import the managers directly:
```python
from oxrpy import OxfordAPI, Servers, Logs, Commands

api = OxfordAPI(server_id="your_server_id", server_key="your_server_key")

servers = Servers(api)
logs = Logs(api)
commands = Commands(api)

# Now use them
server_info = servers.get_server()
kill_logs = logs.get_killlogs()
result = commands.execute_command("kick PlayerOne")
```

## Error Handling
```python
from oxrpy import OxfordAPI, OxfordAPIError

api = OxfordAPI(server_id="your_id", server_key="your_key")

try:
    server_info = api.get_server()
    print("Server info:", server_info)
except OxfordAPIError as e:
    print(f"API Error: {e}")
```

## Features
- Automatic rate limiting (5 requests per second max)
- Comprehensive error handling with custom exceptions
- Request timeouts
- Logging support
- Input validation

## Supported Endpoints

- `get_server()`: Returns general server information.
- `get_players()`: Returns list of current players.
- `get_queue()`: Returns the reserved server queue.
- `get_bans()`: Returns active bans.
- `get_killlogs()`: Returns recent kill logs (max 100 entries).
- `get_commandlogs()`: Returns recent command execution logs.
- `get_modcalls()`: Returns recent moderator call requests.
- `get_vehicles()`: Returns vehicles currently spawned.
- `execute_command(command)`: Executes a permitted command (e.g., "announce Hello!").
`get_robberies()`: Returns the current status of all robbery locations (Name, Alarm, Available).
- `get_radiocalls()`: Returns recent radio calls (last 100).

## API Endpoints
get_server(): Returns general server information.
Example response:
```json
{
  "Name": "Oxford Roleplay",
  "StyledName": "Oxford RP",
  "Description": "UK emergency roleplay server",
  "Tags": ["UK", "RP"],
  "ThemeColour": "#ffffff",
  "OwnerId": 123456789,
  "CurrentPlayers": 18,
  "MaxPlayers": 32,
  "JoinCode": "OXFD-ABCD",
  "CreatedAt": 1700000000,
  "Packages": []
}
```

get_players(): Returns list of current players.
Example response:
```json
[
  {
    "Username": "PlayerOne",
    "DisplayName": "PlayerOne",
    "UserId": 12345,
    "Team": "Civilian",
    "WantedLevel": 0,
    "Permission": "Admin",
    "Callsign": "A12",
    "Location": "Near Oxford City Centre"
  }
]
```

get_queue(): Returns the reserved server queue.
Example response:
```json
{
  "total": 2,
  "users": [12345, 67890]
}
```

get_bans(): Returns active bans.
Example response:
```json
[
  {
    "UserId": 12345,
    "Username": "BannedUser",
    "Reason": "Fail RP",
    "BannedBy": "API",
    "BannedById": 2,
    "Expiry": 1701000000
  }
]
```

get_killlogs(): Returns recent kill logs (maximum 100 entries).
Example response:
```json
[
  {
    "Timestamp": 1700000100,
    "KillerUserId": 123,
    "KillerUsername": "OfficerA",
    "VictimUserId": 456,
    "VictimUsername": "SuspectB",
    "Distance": 42,
    "Weapon": "Taser"
  }
]
```

get_commandlogs(): Returns recent command execution logs.
Example response:
```json
[
  {
    "Timestamp": 1700000200,
    "UserId": 789,
    "Username": "AdminUser",
    "Command": "kick",
    "Args": ["PlayerOne"]
  }
]
```

get_modcalls(): Returns recent moderator call requests.
Example response:
```json
[
  {
    "Timestamp": 1700000300,
    "CallerUserId": 123,
    "CallerUsername": "PlayerOne",
    "CallerDisplayName": "Player One",
    "CaseId": "CASE-001",
    "Responders": [
      {
        "UserId": 789,
        "Username": "ModeratorA"
      }
    ]
  }
]
```

get_vehicles(): Returns vehicles currently spawned in the server.
Example response:
```json
[
  {
    "OwnerUserId": 123,
    "OwnerUsername": "PlayerOne",
    "Registration": "OX12 ABC",
    "Model": "Volvo XC90",
    "Electric": false,
    "ELS": true,
    "ELS_Style": "UK"
  }
]
```

execute_command(command): Executes a permitted command on the server.
Example response:
```json
{
  "message": "Command sent successfully"
}
```

Example response:
```json
[
  {
    "Name": "Berry",
    "Alarm": false,
    "Available": true
  },
  {
    "Name": "Jewellers",
    "Alarm": true,
    "Available": false
  }
]
```

Example response:
```json
[
  {
    "Timestamp": 1765814500,
    "AuthorUserId": 123456789,
    "AuthorUsername": "Officer_Johnson",
    "Location": "City Hall",
    "Description": "Armed robbery in progress",
    "Channel": "Police"
  }
]
```



