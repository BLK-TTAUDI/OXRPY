"""Exceptions raised by oxrpy."""

from __future__ import annotations

import difflib
from typing import Any, List, Optional

# What to do about the API's common errors, matched on the start of its message.
_MESSAGE_HINTS = (
    ("Missing required header: server-key",
     "Pass your server key: OxfordAPI(key), or set OXFD_SERVER_KEY."),
    ("Invalid API key",
     "Check the key in Server Management > External > API Key. If it was regenerated, "
     "the old one stops working within a few seconds."),
    ("This server does not have the API package",
     "The server needs the API package: buy it in Server Management > Packages."),
    ("Invalid app key",
     "Check app_key (it starts with oxa_). It may have been replaced or removed."),
    ("This app key is suspended",
     "Contact Oxford Roleplay about the app key."),
    ("Endpoint not found",
     "Your oxrpy may be out of date: pip install -U oxrpy"),
    ("This endpoint was removed",
     "Upgrade oxrpy: pip install -U oxrpy"),
    ("Too many long commands waiting",
     "Long commands (over about 900 bytes) queue up; wait a few seconds between them."),
    ("Failed to send command",
     "The command wasn't run. Try again in a moment."),
    ("No command with that id",
     "Command results are kept for 7 days. Check the CommandId."),
    ("Server is offline",
     "The server must be online to run commands. Reading data still works while it's offline."),
)

# What to do about a failed command's Code.
_CODE_HINTS = {
    "TARGET_NOT_FOUND": "Nobody matched. Use a Roblox user ID to be exact; names can change.",
    "INVALID_ARGS": "The message shows how the command is used.",
    "FORBIDDEN": "The owner and staff can't be targeted by that command.",
    "PACKAGE_REQUIRED": "The command needs a package (RoleplayKit, FleetKit or AdvancedServer).",
    "RATE_LIMITED": "The game runs at most 15 commands every 10 seconds. run_many() paces them for you.",
    "OFFLINE": "The server must be online to run commands.",
    "UNKNOWN_COMMAND": "See the list of commands: https://docs.oxfd.re/#commands",
}


def hint_for(status: Optional[int], message: str, code: Optional[str] = None, body: Any = None) -> Optional[str]:
    """A short suggestion for fixing an error, or ``None``."""
    if status == 400 and isinstance(body, dict) and body.get("ValidParameters"):
        bad = message.split(":", 1)[-1].strip()
        close = difflib.get_close_matches(bad, [str(p) for p in body["ValidParameters"]], n=1, cutoff=0.6)
        if close:
            return f"Did you mean {close[0]!r}?"
        return "Valid parameters: " + ", ".join(str(p) for p in body["ValidParameters"])
    for prefix, hint in _MESSAGE_HINTS:
        if message.startswith(prefix):
            return hint
    if code and code in _CODE_HINTS:
        return _CODE_HINTS[code]
    if status == 429:
        return "Too many requests. oxrpy already waited and retried; slow down or raise max_retries."
    if status is not None and status >= 500:
        return "A problem on Oxford's side. Try again shortly; https://docs.oxfd.re/#status shows API status."
    return None


class OxfordAPIError(Exception):
    """Base class for every error oxrpy raises.

    Attributes:
        message: The API's ``message`` (or a description of what went wrong).
        status: The HTTP status code, if there was a response.
        code: The API's ``Code`` (e.g. ``"OFFLINE"``, ``"RATE_LIMITED"``), if any.
        body: The decoded JSON body, if there was one.
        hint: A suggestion for fixing it, if oxrpy has one (also shown when the error prints).
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        body: Any = None,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body = body
        self.hint = hint if hint is not None else hint_for(status, message, code, body)

    def __str__(self) -> str:
        parts = []
        if self.status is not None:
            parts.append(str(self.status))
        if self.code:
            parts.append(self.code)
        prefix = " ".join(parts)
        text = f"{prefix}: {self.message}" if prefix else self.message
        return f"{text} (hint: {self.hint})" if self.hint else text


class AuthenticationError(OxfordAPIError):
    """401/403: missing or invalid server key, missing API package, or a bad/suspended app key."""


class BadRequestError(OxfordAPIError):
    """400: an unknown parameter, a bad value, or a malformed command body.

    ``valid_parameters`` lists every parameter ``GET /v1/server`` accepts, when the API sends it.
    """

    @property
    def valid_parameters(self) -> List[str]:
        if isinstance(self.body, dict):
            return list(self.body.get("ValidParameters") or [])
        return []


class NotFoundError(OxfordAPIError):
    """404: no such endpoint, or no command with that id (results are kept for 7 days)."""


class EndpointRemovedError(OxfordAPIError):
    """410: a deprecated endpoint that has been removed."""


class RateLimitError(OxfordAPIError):
    """429: rate limited, and the retries ran out.

    ``retry_after`` is the number of seconds the API asked us to wait.
    """

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerOfflineError(OxfordAPIError):
    """503: the server is offline, so the command could not be run."""


class CommandFailedError(OxfordAPIError):
    """A command reached the server but did not succeed (only raised with ``check=True``).

    ``result`` is the full command result (``CommandId``, ``Status``, ``Code``, ``Message``).
    """

    def __init__(self, result: dict) -> None:
        super().__init__(
            result.get("Message") or "Command failed",
            status=200,
            code=result.get("Code"),
            body=result,
        )
        self.result = result
        self.command_id = result.get("CommandId")
