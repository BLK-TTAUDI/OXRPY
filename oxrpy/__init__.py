"""oxrpy: a Python wrapper for the Oxford Response private server API (https://docs.oxfd.re)."""

__version__ = "2.1.0"

from ._base import (  # noqa: E402
    AUDIT_CATEGORIES,
    BASE_URL,
    LOG_SECTIONS,
    SECTIONS,
    Commands,
    Logs,
    ServerData,
    Servers,
)
from .aio import AsyncLogFollower, AsyncOxfordAPI  # noqa: E402
from .client import OxfordAPI  # noqa: E402
from .commands import TEAMS, format_duration  # noqa: E402
from .errors import (  # noqa: E402
    AuthenticationError,
    BadRequestError,
    CommandFailedError,
    EndpointRemovedError,
    NotFoundError,
    OxfordAPIError,
    RateLimitError,
    ServerOfflineError,
)
from .follower import LogFollower  # noqa: E402
from .ratelimit import AsyncTokenBucket, TokenBucket  # noqa: E402

__all__ = [
    "OxfordAPI",
    "AsyncOxfordAPI",
    "ServerData",
    "LogFollower",
    "AsyncLogFollower",
    "Servers",
    "Logs",
    "Commands",
    "TokenBucket",
    "AsyncTokenBucket",
    "format_duration",
    "TEAMS",
    "OxfordAPIError",
    "AuthenticationError",
    "BadRequestError",
    "CommandFailedError",
    "EndpointRemovedError",
    "NotFoundError",
    "RateLimitError",
    "ServerOfflineError",
    "SECTIONS",
    "LOG_SECTIONS",
    "AUDIT_CATEGORIES",
    "BASE_URL",
    "__version__",
]
