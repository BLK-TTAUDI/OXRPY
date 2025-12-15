# oxrpy
A Python wrapper for the Oxford RP API.

## Installation

Install from PyPI:
```python
pip install oxrpy
```

```python
## Usage
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

## Features
- Automatic rate limiting (5 requests per second max)
- Comprehensive error handling with custom exceptions
- Request timeouts
- Logging support
- Input validation

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

