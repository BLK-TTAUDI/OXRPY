"""Exceptions raised by oxrpy."""

from __future__ import annotations

from typing import Any, List, Optional


class OxfordAPIError(Exception):
    """Base class for every error oxrpy raises.

    Attributes:
        message: The API's ``message`` (or a description of what went wrong).
        status: The HTTP status code, if there was a response.
        code: The API's ``Code`` (e.g. ``"OFFLINE"``, ``"RATE_LIMITED"``), if any.
        body: The decoded JSON body, if there was one.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[str] = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body = body

    def __str__(self) -> str:
        parts = []
        if self.status is not None:
            parts.append(str(self.status))
        if self.code:
            parts.append(self.code)
        prefix = " ".join(parts)
        return f"{prefix}: {self.message}" if prefix else self.message


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
