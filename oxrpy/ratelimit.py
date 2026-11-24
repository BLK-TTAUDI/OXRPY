"""Client-side token buckets, mirroring the API's own limits."""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time
from typing import List, Optional, Tuple


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

    def set_rate(self, rate: float, capacity: Optional[float] = None) -> None:
        """Change the steady rate (and the burst), e.g. when the API reports a different limit."""
        if rate <= 0:
            raise ValueError("rate must be positive")
        with self._lock:
            self._refill(time.monotonic())
            self.rate = float(rate)
            if capacity is not None:
                self.capacity = float(max(1.0, capacity))
                self._tokens = min(self._tokens, self.capacity)

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
    """The asyncio version of :class:`TokenBucket`. Waiting doesn't block the event loop.

    Waiters are served in order instead of racing for each token, so with many servers
    sharing one limit nobody is starved. ``priority=0`` (requests you make yourself, like a
    Discord command's lookup) goes ahead of ``priority=1`` (background polling).
    """

    def __init__(self, rate: float, capacity: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate)
        self.capacity = float(max(1.0, capacity))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._waiters: List[Tuple[int, int, "asyncio.Future[bool]"]] = []
        self._order = itertools.count()
        self._dispatcher: "Optional[asyncio.Task[None]]" = None

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    @property
    def waiting(self) -> int:
        """How many requests are queued for a token right now."""
        return sum(1 for *_, fut in self._waiters if not fut.done())

    def set_rate(self, rate: float, capacity: Optional[float] = None) -> None:
        """Change the steady rate (and the burst), e.g. when the API reports a different limit."""
        if rate <= 0:
            raise ValueError("rate must be positive")
        self._refill()
        self.rate = float(rate)
        if capacity is not None:
            self.capacity = float(max(1.0, capacity))
            self._tokens = min(self._tokens, self.capacity)

    def try_acquire(self) -> bool:
        self._refill()
        if self._tokens >= 1 and not self._waiters:  # don't jump the queue
            self._tokens -= 1
            return True
        return False

    async def acquire(self, timeout: Optional[float] = None, *, priority: int = 0) -> bool:
        """Wait for a token, in turn. Returns ``False`` if ``timeout`` seconds pass first."""
        if self.try_acquire():
            return True
        future: "asyncio.Future[bool]" = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._order), future))
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.get_running_loop().create_task(self._dispatch())
        try:
            if timeout is None:
                return await future
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return False

    async def _dispatch(self) -> None:
        """Hand out tokens to the waiters, best priority first, then first come first served."""
        while self._waiters:
            if self._waiters[0][2].done():  # gave up (timed out or cancelled)
                heapq.heappop(self._waiters)
                continue
            self._refill()
            if self._tokens >= 1:
                self._tokens -= 1
                heapq.heappop(self._waiters)[2].set_result(True)
                continue
            await asyncio.sleep((1 - self._tokens) / self.rate)

    def drain(self) -> None:
        self._tokens = 0
        self._updated = time.monotonic()
