"""Client-side token buckets, mirroring the API's own limits."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Optional


class TokenBucket:
    """A thread-safe token bucket: ``rate`` tokens a second, holding up to ``capacity``."""

    def __init__(self, rate: float, capacity: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate)
        self.capacity = float(max(1.0, capacity))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self, now: float) -> None:
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    def try_acquire(self) -> bool:
        """Take a token if one is available right now."""
        with self._lock:
            self._refill(time.monotonic())
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """Wait for a token. Returns ``False`` if ``timeout`` seconds pass first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= 1:
                    self._tokens -= 1
                    return True
                wait = (1 - self._tokens) / self.rate
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)
            time.sleep(wait)

    def drain(self) -> None:
        """Empty the bucket, e.g. after the API answered 429."""
        with self._lock:
            self._tokens = 0
            self._updated = time.monotonic()


class AsyncTokenBucket:
    """The asyncio version of :class:`TokenBucket`. Waiting doesn't block the event loop."""

    def __init__(self, rate: float, capacity: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate)
        self.capacity = float(max(1.0, capacity))
        self._tokens = self.capacity
        self._updated = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    def try_acquire(self) -> bool:
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """Wait for a token. Returns ``False`` if ``timeout`` seconds pass first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            # No await between the check and the take, so this is safe without a lock.
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            wait = (1 - self._tokens) / self.rate
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)
            await asyncio.sleep(wait)

    def drain(self) -> None:
        self._tokens = 0
        self._updated = time.monotonic()
