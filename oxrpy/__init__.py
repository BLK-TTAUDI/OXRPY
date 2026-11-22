"""oxrpy: a Python wrapper for the Oxford Response private server API (https://docs.oxfd.re)."""

__version__ = "2.0.0"

from .client import (  # noqa: E402
    AUDIT_CATEGORIES,
    BASE_URL,
    LOG_SECTIONS,
    SECTIONS,
    Commands,
    Logs,
    OxfordAPI,
    ServerData,
    Servers,
)
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
from .ratelimit import TokenBucket  # noqa: E402

__all__ = [
    "OxfordAPI",
    "ServerData",
    "LogFollower",
    "Servers",
    "Logs",
    "Commands",
    "TokenBucket",
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
