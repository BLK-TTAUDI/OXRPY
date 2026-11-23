"""Shapes of the data the API returns, so editors can autocomplete field names.

These are ``TypedDict``s: at runtime everything is still a plain ``dict``, so nothing changes
for your code. They just tell your editor (and type checkers like mypy or Pylance) which keys
exist, so ``player["Usernmae"]`` gets flagged before you run it.

Every class is ``total=False`` because the API can leave fields out (a player who's still
loading in only has ``UserId``, ``Username`` and ``DisplayName``) and adds new fields over time.
Anything the API marks as "or ``null``" is ``Optional``.

Field reference: https://docs.oxfd.re/#reference
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

#: ``[x, y, z]`` in studs.
Position = List[float]

TeamName = Literal["Civilian", "Police", "Ambulance", "Highways", "Fire", "Jailed"]


# --------------------------------------------------------------------------- top level


class ServerInfo(TypedDict, total=False):
    """``data["Server"]``: the server's core details."""

    ServerId: str
    Name: str
    OwnerId: int
    OwnerUsername: Optional[str]
    CurrentPlayers: int
    MaxPlayers: int
    Access: Literal["Listed", "Code", "StaffOnly"]
    JoinCode: Optional[str]
    Packages: List[str]
    StartedAt: Optional[int]
    Uptime: Optional[int]
    PlaceVersion: Optional[int]
    JobId: Optional[str]
    CommandChannel: Optional[str]
    StyledName: Optional[str]
    Description: Optional[str]
    Tags: List[str]
    ThemeColour: Optional[str]
    Logo: Optional[str]
    CreatedAt: Optional[int]
    MatchmakingType: Optional[str]
    ApiVersion: Optional[Any]


# --------------------------------------------------------------------------- players


class Location(TypedDict, total=False):
    Road: Optional[str]
    Area: Optional[str]
    Grid: Optional[str]
    Address: Optional[str]


class Custody(TypedDict, total=False):
    By: Optional[int]
    Mode: Optional[str]
    DeadlineAt: Optional[int]
    StaffCustody: bool


class Wanted(TypedDict, total=False):
    Level: int
    EndsAt: Optional[int]
    Paused: bool
    Offences: List[Any]


class Jailed(TypedDict, total=False):
    EndsAt: Optional[int]


class PlayerVehicle(TypedDict, total=False):
    Plate: str
    Seat: Literal["Driver", "FrontPassenger", "RearLeft", "RearRight", "Rear"]
    Owner: bool


class Holding(TypedDict, total=False):
    Item: str
    Aiming: bool
    Ammo: Optional[int]
    Spare: Optional[int]


class Unit(TypedDict, total=False):
    Status: Optional[str]
    IncidentId: Optional[str]
    ControlOperator: bool


class CivilianJob(TypedDict, total=False):
    Job: str
    Stage: Optional[str]


class Player(TypedDict, total=False):
    """One entry in ``Players``."""

    UserId: int
    Username: str
    DisplayName: str
    Team: Optional[str]
    Callsign: Optional[str]
    Rank: Optional[str]
    RankId: Optional[str]
    Position: Optional[Position]
    Heading: Optional[int]
    Location: Optional[Location]
    Health: Optional[int]
    MaxHealth: Optional[int]
    Downed: bool
    DownedCall: bool
    Tased: bool
    Invincible: bool
    Custody: Optional[Custody]
    Wanted: Optional[Wanted]
    Jailed: Optional[Jailed]
    Vehicle: Optional[PlayerVehicle]
    Holding: Optional[Holding]
    Stance: Optional[Literal["Standing", "Running", "Crouching", "Ragdolled"]]
    Unit: Optional[Unit]
    Carrying: Optional[str]
    Job: Optional[CivilianJob]
    Disguised: bool
    SessionSeconds: Optional[int]
    AccountAgeDays: Optional[int]


class Tracks(TypedDict, total=False):
    """``Tracks``: samples are ``[t, x, z, heading]`` with ``t`` in seconds after ``From``."""

    From: int
    Players: Dict[str, List[List[float]]]
    Vehicles: Dict[str, List[List[float]]]


# --------------------------------------------------------------------------- vehicles


class Colour(TypedDict, total=False):
    Name: str
    Hex: str


class CustomVehicleRef(TypedDict, total=False):
    Id: str
    Name: str


class Fuel(TypedDict, total=False):
    Litres: float
    Capacity: float


class Tyres(TypedDict, total=False):
    FL: Literal["OK", "Popped"]
    FR: Literal["OK", "Popped"]
    RL: Literal["OK", "Popped"]
    RR: Literal["OK", "Popped"]


class Lights(TypedDict, total=False):
    Headlights: Literal["Off", "Dipped", "Full"]
    Indicator: Literal["Off", "Left", "Right", "Hazards"]
    Braking: bool
    Reversing: bool


class ElsPanel(TypedDict, total=False):
    FrontBlues: bool
    RearBlues: bool
    GrilleBlues: bool
    RearReds: bool
    FrontSpots: bool
    TakeDown: bool
    Cruise: bool
    SlowPattern: bool
    LeftAlley: bool
    RightAlley: bool
    Rumbler: bool


class Siren(TypedDict, total=False):
    Armed: bool
    Tone: Optional[Literal["Wail", "Yelp", "Phaser"]]
    Bullhorn: bool


class Els(TypedDict, total=False):
    """Emergency lights and siren."""

    Style: Literal["Blue", "Amber", "Red"]
    HasLightbar: bool
    HasAlleys: bool
    Mode: Literal["999", "AtScene", "Custom", "Off"]
    Active: bool
    Panel: ElsPanel
    Siren: Siren


class Occupant(TypedDict, total=False):
    Seat: str
    UserId: int
    Detained: bool


class Appliance(TypedDict, total=False):
    TankPercent: float
    InFlow: float
    OutFlow: float
    PumpDoorOpen: bool
    LinesOut: int
    SupplyConnected: bool


class Vehicle(TypedDict, total=False):
    """One entry in ``Vehicles``."""

    Plate: str
    OwnerId: int
    Team: Optional[str]
    Model: str
    Livery: Optional[str]
    Custom: Optional[CustomVehicleRef]
    Colour: Optional[Colour]
    Electric: bool
    Position: Optional[Position]
    Heading: Optional[int]
    SpeedMph: Optional[int]
    Location: Optional[Location]
    EngineOn: bool
    Locked: bool
    Horn: bool
    Anpr: bool
    Health: Optional[int]
    Smoking: bool
    Fuel: Optional[Fuel]
    Tyres: Optional[Tyres]
    Lights: Optional[Lights]
    Els: Optional[Els]
    Occupants: List[Occupant]
    Towing: Optional[Dict[str, Any]]
    Cargo: List[str]
    Appliance: Optional[Appliance]
    SpawnedAt: Optional[int]


# --------------------------------------------------------------------------- world


class World(TypedDict, total=False):
    Weather: Literal["Clear", "Rain", "Snow", "Thunderstorm"]
    WeatherLocked: bool
    TemperatureC: Optional[float]
    Clock: str
    ClockMinutes: int
    ClockLocked: bool
    Night: bool
    StreetLights: bool
    SnowCover: float
    Season: Optional[str]
    SpeedLimitMph: Optional[int]
    StickyMessage: Optional[str]
    CountdownEndsAt: Optional[int]
    NpcCallouts: bool


class TeamAccess(TypedDict, total=False):
    Staff: bool
    StaffRanks: Optional[List[str]]
    Groups: Optional[List[str]]


class TeamStatus(TypedDict, total=False):
    """One team in ``Teams`` (keyed by team name)."""

    Players: Optional[int]
    Limit: Optional[int]
    DefaultLimit: Optional[int]
    CustomLimit: bool
    Access: Optional[TeamAccess]


class QueueEntry(TypedDict, total=False):
    UserId: int
    JoinedAt: int
    Priority: int


class Robbery(TypedDict, total=False):
    Name: str
    DisplayName: str
    State: Literal["Available", "Robbery", "Cooldown", "OnFire"]
    Stage: Optional[str]
    Alarm: bool
    Robbers: List[int]
    LootRemaining: Optional[int]
    OpensAt: Optional[int]
    Position: Optional[Position]


class Atm(TypedDict, total=False):
    Name: str
    Available: bool
    Alarm: bool
    RobbedBy: Optional[int]
    Position: Optional[Position]


class Incident(TypedDict, total=False):
    Id: str
    Type: str
    Team: str
    Priority: int
    Status: str
    Place: Optional[str]
    Position: Optional[Position]
    Count: int
    Text: Optional[str]
    Responders: List[int]
    Assigned: List[int]
    CreatedAt: int
    LastAt: int


class IncidentUnit(TypedDict, total=False):
    UserId: int
    Callsign: Optional[str]
    Team: str
    Status: Optional[str]
    IncidentId: Optional[str]


class Incidents(TypedDict, total=False):
    Open: List[Incident]
    Units: List[IncidentUnit]
    Operators: List[Dict[str, Any]]
    Timeline: List[Dict[str, Any]]


# --------------------------------------------------------------------------- server


class StaffMember(TypedDict, total=False):
    UserId: int
    Username: Optional[str]
    RankId: str
    Rank: str
    Online: bool


class GroupSync(TypedDict, total=False):
    GroupId: int
    Rank: Optional[int]


class Rank(TypedDict, total=False):
    Id: str
    Name: str
    Priority: int
    Sync: GroupSync


class Staff(TypedDict, total=False):
    """``Staff``."""

    OwnerId: int
    Staff: List[StaffMember]
    Ranks: List[Rank]


class Group(TypedDict, total=False):
    Id: str
    Name: str
    Sync: GroupSync
    Members: List[int]


class Ban(TypedDict, total=False):
    UserId: int
    Username: Optional[str]
    Reason: Optional[str]
    BannedBy: Optional[str]
    BannedById: Optional[int]
    ExpiresAt: Optional[int]


class BansPage(TypedDict, total=False):
    Total: int
    Offset: int
    List: List[Ban]


class AuditEntry(TypedDict, total=False):
    Number: int
    Timestamp: int
    UserId: int
    Username: str
    Command: str
    Category: str
    Args: List[str]
    Description: str


class AuditPage(TypedDict, total=False):
    Entries: List[AuditEntry]
    Next: Optional[int]
    Total: int


# --------------------------------------------------------------------------- logs


class LogEntry(TypedDict, total=False):
    """Fields every log entry has."""

    Seq: int
    Id: str
    Type: str
    At: float


class KillLog(LogEntry, total=False):
    KillerUserId: int
    KillerUsername: str
    VictimUserId: int
    VictimUsername: str
    Distance: Optional[float]
    Weapon: Optional[str]
    KillerPosition: Optional[Position]
    VictimPosition: Optional[Position]
    Part: Optional[Literal["Head", "Torso", "Limb"]]
    Headshot: bool


class ModCallResponder(TypedDict, total=False):
    UserId: int
    Username: str
    Timestamp: int


class ModCall(LogEntry, total=False):
    CallerUserId: int
    CallerUsername: str
    CallerDisplayName: str
    CaseId: str
    Responders: List[ModCallResponder]
    UpdatedAt: Optional[int]
    ResolvedAt: Optional[int]
    ResolvedBy: Optional[int]
    ResolvedByUsername: Optional[str]


class RadioCall(LogEntry, total=False):
    UserId: int
    Username: str
    Channel: str
    Callsign: Optional[str]
    Location: Optional[str]
    Coordinates: Optional[Position]
    Description: Optional[str]


class JoinLog(LogEntry, total=False):
    UserId: int
    Username: str
    DisplayName: str
    JoinType: Literal["Join", "Leave"]


class CommandLog(LogEntry, total=False):
    UserId: int
    Username: str
    Command: str
    Category: str
    Args: List[str]
    Description: str


class CommandResultLog(LogEntry, total=False):
    Command: str
    SentAt: int
    Success: Optional[bool]
    Code: Optional[str]
    Message: Optional[str]
    Status: Literal["Succeeded", "Failed", "Pending", "NoResult"]


class Event(LogEntry, total=False):
    """A game event. Which fields are present depends on ``Type``: see
    https://docs.oxfd.re/#events. The common ones are listed here."""

    UserId: int
    Username: str
    By: int
    ByUsername: str
    From: Any
    To: Any
    Position: Position
    Plate: str
    Model: str
    Weapon: str
    Name: str
    Team: str
    Reason: str
    Amount: float
    SpeedMph: int
    Limit: int
    Fine: int
    Place: str
    IncidentId: str
    Status: str
    Channel: str


class ShotHit(TypedDict, total=False):
    UserId: int
    Part: Literal["Head", "Torso", "Limb"]
    Damage: float
    HpAfter: float
    Downed: bool
    World: Literal["Glass", "Tyre", "World"]
    At: Position
    Blocked: bool


class Shot(TypedDict, total=False):
    Seq: int
    At: float
    Until: float
    Burst: bool
    Count: int
    Hits: int
    Shooter: int
    Team: str
    Weapon: str
    From: Position
    To: Position
    Pellets: int
    Hit: Optional[ShotHit]


# --------------------------------------------------------------------------- commands and status


class CommandResult(TypedDict, total=False):
    """What ``run_command`` and the helpers return."""

    CommandId: str
    Status: Literal["Succeeded", "Failed", "Pending"]
    Code: Literal[
        "OK", "TARGET_NOT_FOUND", "INVALID_ARGS", "FORBIDDEN", "PACKAGE_REQUIRED",
        "RATE_LIMITED", "OFFLINE", "UNKNOWN_COMMAND", "FAILED",
    ]
    Message: str


class CommandStatus(TypedDict, total=False):
    """What ``get_command`` returns (the API's older shape, lower-case ``Status``)."""

    Id: str
    Command: str
    SentAt: int
    Timestamp: Optional[int]
    Success: Optional[bool]
    Message: Optional[str]
    Status: Literal["succeeded", "failed", "pending", "no_result"]


class ApiStatus(TypedDict, total=False):
    Status: Literal["operational", "degraded"]
    GeneratedAt: int
    StartedAt: int
    UptimeSeconds: int
    LastHour: Dict[str, float]
    Uptime: Dict[str, Any]


#: Settings, the Catalogue and a few world sections vary a lot; they're plain dicts.
Settings = Dict[str, Any]
Catalogue = Dict[str, Any]
Teams = Dict[str, TeamStatus]
AnyEntry = Union[KillLog, ModCall, RadioCall, JoinLog, CommandLog, CommandResultLog, Event, Shot]
