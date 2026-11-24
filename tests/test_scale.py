"""Tests for apps that follow many servers: the fair rate limiter, limits that follow what Oxford
reports, cached reads, and AsyncServerPool's stats, verify() and update_key()."""

import asyncio
import time

import httpx
import pytest

import oxrpy
from oxrpy import AsyncOxfordAPI, AsyncServerPool, AsyncTokenBucket, AuthenticationError, PoolStats
from test_client import TOP


# ---------------------------------------------------------------- the fair limiter

def test_waiters_are_served_in_order_with_own_requests_first():
    async def main():
        bucket = AsyncTokenBucket(50, 1)
        assert await bucket.acquire()  # uses the only token
        order = []

        async def take(label, priority):
            await bucket.acquire(priority=priority)
            order.append(label)

        tasks = [asyncio.create_task(take(f"poll{i}", 1)) for i in range(3)]
        await asyncio.sleep(0)
        tasks.append(asyncio.create_task(take("mine", 0)))  # arrives last, goes first
        await asyncio.gather(*tasks)
        assert order == ["mine", "poll0", "poll1", "poll2"]

    asyncio.run(main())


def test_a_timed_out_waiter_doesnt_hold_up_the_rest():
    async def main():
        bucket = AsyncTokenBucket(5, 1)
        assert await bucket.acquire()
        assert await bucket.acquire(timeout=0.01) is False
        assert bucket.waiting == 0
        assert await bucket.acquire(timeout=1)

    asyncio.run(main())


def test_no_jumping_the_queue():
    async def main():
        bucket = AsyncTokenBucket(20, 1)
        assert await bucket.acquire()
        waiter = asyncio.create_task(bucket.acquire())
        await asyncio.sleep(0)
        await asyncio.sleep(0.06)  # a token is back, but someone's queued for it
        assert await waiter
        assert bucket.try_acquire() is False

    asyncio.run(main())


def test_set_rate():
    bucket = AsyncTokenBucket(20, 40)
    bucket.set_rate(100, 200)
    assert (bucket.rate, bucket.capacity) == (100, 200)
    with pytest.raises(ValueError):
        bucket.set_rate(0)
    sync = oxrpy.TokenBucket(1, 2)
    sync.set_rate(3, 6)
    assert (sync.rate, sync.capacity) == (3, 6)


# ---------------------------------------------------------------- limits that follow Oxford

def fake(handler, **kw):
    return AsyncOxfordAPI("sk_test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


def test_app_key_follows_the_limit_oxford_reports():
    async def main():
        api = fake(lambda r: httpx.Response(200, json=TOP, headers={"X-RateLimit-Limit": "100"}),
                   app_key="oxa_" + "a" * 40)
        assert api._limiters["data"].rate == 20  # standard tier to start with
        await api.get_players()
        assert api._limiters["data"].rate == 100
        assert api._limiters["get"].rate == 100  # all GETs share one limit with an app key
        assert api._limiters["data"].capacity == 200

    asyncio.run(main())


def test_without_an_app_key_the_limits_stay_put():
    async def main():
        api = fake(lambda r: httpx.Response(200, json=TOP, headers={"X-RateLimit-Limit": "30"}))
        await api.get_players()
        assert api._limiters["data"].rate == 1

    asyncio.run(main())


# ---------------------------------------------------------------- cached reads

def test_max_age_answers_from_latest_without_a_request():
    async def main():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=dict(TOP, Players=[{"Username": "a"}]))

        api = fake(handler, rate_limit="none")
        assert await api.get_players() == [{"Username": "a"}]
        assert await api.get_players(max_age=5) == [{"Username": "a"}]
        assert len(calls) == 1
        await api.get_players()  # no max_age: always fetches
        assert len(calls) == 2

    asyncio.run(main())


# ---------------------------------------------------------------- the pool

@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0.01)
    monkeypatch.setattr(oxrpy.follower, "error_delay", lambda exc, n: 0.01)


def pool_from(handler, **kw):
    kw.setdefault("rate_limit", "none")
    return AsyncServerPool(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)


def entries(seq):
    return dict(TOP, Cursor=seq, Server={"Name": "RP", "CurrentPlayers": 3},
                KillLogs=[{"Seq": seq, "Type": "Kill"}])


def test_stats(quick):
    async def main():
        seqs = {}

        def handler(request):
            key = request.headers["server-key"]
            seqs[key] = seqs.get(key, 0) + 1
            return httpx.Response(200, json=entries(seqs[key]))

        pool = pool_from(handler)
        pool.add("a", "key-a")
        pool.add("b", "key-b")
        pool.on("Kill", lambda server, kill: None)
        runner = asyncio.create_task(pool.run_forever())
        await asyncio.sleep(0.3)
        stats = pool.stats
        pool.stop()
        await runner

        assert isinstance(stats, PoolStats)
        assert (stats.servers, stats.following, stats.failed) == (2, 2, 0)
        assert stats.read_limit is None  # rate_limit="none"
        assert stats.requests_per_second > 0
        assert 0 < stats.average_interval < 0.3
        assert stats.slowest_interval >= stats.average_interval
        a = stats.per_server["a"]
        assert a.polls >= 3 and a.online is True and a.players == 3 and a.failed is None

    asyncio.run(main())


def test_read_limit():
    pool = AsyncServerPool()
    assert pool.read_limit == 30  # the per-IP limit
    assert AsyncServerPool(app_key="oxa_" + "a" * 40).read_limit == 20
    assert AsyncServerPool(rate_limit="none").read_limit is None


def test_verify():
    async def main():
        def handler(request):
            if request.headers["server-key"] == "good":
                return httpx.Response(200, json=dict(TOP, Server={"Name": "Test RP", "OwnerId": 1}))
            return httpx.Response(403, json={"message": "Invalid server key"})

        pool = pool_from(handler)
        assert (await pool.verify("good"))["Name"] == "Test RP"
        with pytest.raises(AuthenticationError):
            await pool.verify("bad")
        assert len(pool) == 0  # verify doesn't add anything

    asyncio.run(main())


def test_update_key_brings_a_failed_server_back(quick):
    async def main():
        def handler(request):
            if request.headers["server-key"] == "old":
                return httpx.Response(403, json={"message": "Invalid server key"})
            return httpx.Response(200, json=entries(9))

        pool = pool_from(handler)
        pool.add("a", "old")
        errors = []
        pool.on("error", lambda server, exc: errors.append(server))
        pool.on("poll", lambda server, data: None)
        runner = asyncio.create_task(pool.run_forever())
        await asyncio.sleep(0.1)
        assert "a" in pool.failed and errors == ["a"]
        assert pool.stats.per_server["a"].failed is not None

        await pool.update_key("a", "new")
        await asyncio.sleep(0.1)
        stats = pool.stats.per_server["a"]
        pool.stop()
        await runner
        assert "a" not in pool.failed
        assert stats.failed is None and stats.polls >= 1

    asyncio.run(main())


def test_busy_pool_shares_the_limit_fairly(monkeypatch):
    """60 servers on a limit of 60 requests a second, each wanting a poll every 0.2s (300 a
    second): every server still gets its turn, about as often as the others."""
    monkeypatch.setattr(oxrpy.pool, "IP_REQUESTS_PER_SECOND", 60)
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0.2)

    async def main():
        counts = {}

        def handler(request):
            key = request.headers["server-key"]
            counts[key] = counts.get(key, 0) + 1
            return httpx.Response(200, json=TOP)

        pool = pool_from(handler, rate_limit="auto")
        for i in range(60):
            pool.add(f"s{i}", f"key-{i}")
        pool.on("poll", lambda server, data: None)
        runner = asyncio.create_task(pool.run_forever())
        await asyncio.sleep(2.5)
        stats = pool.stats
        pool.stop()
        await runner

        polls = sorted(counts.values())
        assert len(polls) == 60
        assert sum(polls) <= 60 * 2.5 + 60 + 5  # within the per-IP limit (plus its starting burst)
        assert polls[-1] - polls[0] <= 1  # fair: nobody got far more turns than anyone else
        assert stats.waiting > 0  # more demand than limit, so requests queue

    asyncio.run(main())


def test_own_requests_go_ahead_of_a_busy_pool(monkeypatch):
    monkeypatch.setattr(oxrpy.pool, "IP_REQUESTS_PER_SECOND", 20)
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0.05)

    async def main():
        pool = pool_from(lambda r: httpx.Response(200, json=dict(TOP, Players=[])), rate_limit="auto",
                         app_key="oxa_" + "a" * 40)  # one shared limit, as for a big bot
        for i in range(40):
            pool.add(f"s{i}", f"key-{i}")
        pool.on("poll", lambda server, data: None)
        runner = asyncio.create_task(pool.run_forever())
        await asyncio.sleep(0.5)  # the queue is full of polls by now
        started = time.monotonic()
        await pool["s7"].get_players()  # a Discord command's lookup, say
        waited = time.monotonic() - started
        pool.stop()
        await runner
        assert waited < 0.2  # one slot, not the 40 polls ahead of it

    asyncio.run(main())


def test_stops_promptly_even_with_polls_queued(monkeypatch):
    monkeypatch.setattr(oxrpy.pool, "IP_REQUESTS_PER_SECOND", 5)
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0.01)

    async def main():
        pool = pool_from(lambda r: httpx.Response(200, json=TOP), rate_limit="auto")
        for i in range(100):
            pool.add(f"s{i}", f"key-{i}")
        pool.on("poll", lambda server, data: None)
        runner = asyncio.create_task(pool.run_forever())
        await asyncio.sleep(0.2)
        started = time.monotonic()
        pool.stop()
        await runner
        assert time.monotonic() - started < 0.5  # not 100 queued polls at 5 a second
        assert pool.stats.waiting == 0

    asyncio.run(main())
