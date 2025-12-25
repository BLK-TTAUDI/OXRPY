# oxrpy
A Python wrapper for the Oxford Response API.

## Installation

Install from PyPI:
```
pip install oxrpy
```

## Usage
```python
from oxrpy import OxfordAPI

# Initialize with your server key (server-id is no longer required)
api = OxfordAPI(server_key="your_server_key", rate_limit="auto")

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

### Advanced Configuration
```python
# Default rate limiting (recommended for most users) - ~29 requests/second with burst capacity
# Uses token bucket algorithm for smooth throttling and burst handling
api = OxfordAPI(server_key="your_server_key")
# or explicitly:
api = OxfordAPI(server_key="your_server_key", rate_limit="auto")

# For heavy command usage (execute_command), use stricter rate limiting
api = OxfordAPI(server_key="your_server_key", rate_limit=1.0)

# Disable rate limiting entirely (use with caution)
api = OxfordAPI(server_key="your_server_key", rate_limit="none")

# Custom rate limiting (specify seconds between requests)
api = OxfordAPI(server_key="your_server_key", rate_limit=0.5)  # 0.5 seconds

# Configure retry behavior for rate-limited requests
api = OxfordAPI(
    server_key="your_server_key", 
    rate_limit="auto",
    max_retries=5  # Retry up to 5 times on rate limit errors
)

# Legacy usage with server-id (still supported for backward compatibility)
api = OxfordAPI(server_key="your_server_key", server_id="your_server_id")
```

You can also import the managers directly:
```python
from oxrpy import OxfordAPI, Servers, Logs, Commands

api = OxfordAPI(server_key="your_server_key", rate_limit="auto")

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
from oxrpy import OxfordAPI, OxfordAPIError, RateLimitError

api = OxfordAPI(server_key="your_key")

try:
    server_info = api.get_server()
    print("Server info:", server_info)
except RateLimitError as e:
    print(f"Rate limit exceeded: {e}")
    # Handle rate limiting (e.g., wait and retry)
except OxfordAPIError as e:
    print(f"API Error: {e}")
```

## Features
- **Advanced Rate Limiting**: Token bucket algorithm with burst capacity and automatic retries
- **Configurable Retry Logic**: Exponential backoff for rate-limited requests
- **Separate Command Limiting**: Stricter 1/sec limit for command execution endpoints
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
- `get_joinlogs()`: Returns recent player join/leave logs.
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

get_joinlogs(): Returns recent player join/leave logs.
Example response:
```json
[
  {
    "Timestamp": 1700000250,
    "UserId": 12345,
    "Username": "PlayerOne",
    "Action": "joined"
  },
  {
    "Timestamp": 1700000260,
    "UserId": 67890,
    "Username": "PlayerTwo",
    "Action": "left"
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

get_robberies(): Returns the current status of all robbery locations.
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

get_radiocalls(): Returns recent radio calls.
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





