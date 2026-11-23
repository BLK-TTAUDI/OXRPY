"""Tests for 2.3: saving/resuming the log position, and AsyncServerPool."""

import asyncio
import json

import httpx
import pytest

import oxrpy
from oxrpy import AsyncServerPool, FileState
from test_client import TOP, client, make_response
from test_features import OK


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0)
    monkeypatch.setattr(oxrpy.follower, "error_delay", lambda exc, n: 0)
    monkeypatch.setattr(oxrpy.client.time, "sleep", lambda s: None)


def kills(cursor, *seqs):
    return dict(TOP, Cursor=cursor, KillLogs=[{"Seq": s, "Type": "Kill"} for s in sorted(seqs, reverse=True)])


# ---------------------------------------------------------------- saving and resuming

def test_run_forever_saves_and_resumes(tmp_path):
    path = tmp_path / "state" / "cursor.json"

    # First run: starts fresh (skips the backlog), handles kill 6, then stops.
    api, _ = client(make_response(body=kills(5, 4, 5)), make_response(body=kills(6, 6)))
    seen = []

    @api.on("Kill")
    def first(kill):
        seen.append(kill["Seq"])
        api.stop()

    api.run_forever(save_to=path)
    assert seen == [6]
    saved = json.loads(path.read_text())
    assert saved["Cursor"] == 6 and saved["Handled"] == {"KillLogs": 6}

    # Second run ("after a restart"): picks up from 6, so kills 7 and 8, which happened while it
    # was down, are handled and nothing old is replayed.
    api2, session2 = client(make_response(body=kills(8, 6, 7, 8)))
    seen2 = []

    @api2.on("Kill")
    def second(kill):
        seen2.append(kill["Seq"])
        if kill["Seq"] == 8:
            api2.stop()

    api2.run_forever(save_to=path)
    assert seen2 == [7, 8]
    assert session2.calls[0]["params"]["Since"] == "6"
    assert json.loads(path.read_text())["Cursor"] == 8


def test_position_is_saved_only_after_handlers_ran(tmp_path):
    path = tmp_path / "cursor.json"
    api, _ = client(make_response(body=kills(1, 1)), make_response(body=kills(2, 2)))
    follower = api.follow("KillLogs", save_to=path)
    loop = iter(follower)
    next(loop)
    assert not path.exists()            # still handling the first poll
    next(loop)
    assert json.loads(path.read_text())["Cursor"] == 1


def test_custom_store_and_bad_files(tmp_path):
    class Memory:
        def __init__(self):
            self.state = {"Version": 1, "Cursor": 40, "Handled": {"Events": 40}}

        def load(self):
            return self.state

        def save(self, state):
            self.state = state

    store = Memory()
    api, session = client(make_response(body=dict(TOP, Cursor=41, Events=[{"Seq": 41, "Type": "Downed"}])))
    follower = api.follow("Events", save_to=store)
    assert follower.resumed and follower.cursor == 40
    data, new = follower.poll()
    follower.save()
    assert session.calls[0]["params"]["Since"] == "40"
    assert store.state["Cursor"] == 41

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    fresh = api.follow("Events", save_to=broken)
    assert fresh.cursor is None and not fresh.resumed

    with pytest.raises(TypeError):
        api.follow("Events", save_to=123)


def test_file_state_round_trip(tmp_path):
    store = FileState(tmp_path / "a" / "b.json")
    assert store.load() is None
    store.save({"Cursor": 3})
    assert store.load() == {"Cursor": 3}
    assert [p.name for p in (tmp_path / "a").iterdir()] == ["b.json"]   # no temp files left


def test_async_run_forever_resumes(tmp_path):
    path = tmp_path / "cursor.json"
    path.write_text(json.dumps({"Version": 1, "Cursor": 10, "Handled": {"KillLogs": 10}}))

    async def main():
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=kills(11, 10, 11))

        api = oxrpy.AsyncOxfordAPI("k", rate_limit="none",
                                   client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        seen = []

        @api.on("Kill")
        def on_kill(kill):
            seen.append(kill["Seq"])
            api.stop()

        await asyncio.wait_for(api.run_forever(save_to=path), 5)
        assert seen == [11]
        assert calls[0].url.params["Since"] == "10"
        assert json.loads(path.read_text())["Cursor"] == 11
        await api.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------- AsyncServerPool

def pool_with(routes, **kw):
    """A pool whose fake API answers by server key: routes[key] is a list of (status, body)."""
    calls = []

    def handler(request):
        key = request.headers["server-key"]
        calls.append((key, request))
        queue = routes[key]
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, json=body)

    kw.setdefault("rate_limit", "none")
    pool = AsyncServerPool(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)
    return pool, calls


def test_pool_runs_handlers_for_every_server():
    async def main():
        pool, calls = pool_with({
            "key-a": [(200, kills(1, 1)), (200, kills(2, 2))],
            "key-b": [(200, kills(7, 7)), (200, kills(9, 8, 9))],
        })
        pool.add("a", "key-a")
        pool.add("b", "key-b")
        seen = []

        @pool.on("Kill")
        async def on_kill(server, kill):
            seen.append((server, kill["Seq"]))
            if len(seen) == 3:
                pool.stop()

        await asyncio.wait_for(pool.run_forever(), 5)
        assert sorted(seen) == [("a", 2), ("b", 8), ("b", 9)]
        assert {key for key, _ in calls} == {"key-a", "key-b"}
        await pool.aclose()

    asyncio.run(main())


def test_pool_drops_a_server_whose_key_stops_working():
    async def main():
        pool, _ = pool_with({
            "good": [(200, kills(1, 1)), (200, kills(2, 2))],
            "revoked": [(403, {"message": "Invalid API key"})],
        })
        pool.add("good", "good")
        pool.add("revoked", "revoked")
        errors, seen = [], []
        pool.on("error", lambda server, exc: errors.append((server, exc.status)))

        @pool.on("Kill")
        def on_kill(server, kill):
            seen.append(server)
            pool.stop()

        await asyncio.wait_for(pool.run_forever(), 5)
        assert errors == [("revoked", 403)]
        assert list(pool.failed) == ["revoked"]
        assert seen == ["good"]
        await pool.aclose()

    asyncio.run(main())


def test_pool_shares_rate_limits_with_an_app_key():
    pool = AsyncServerPool(app_key="oxa_x", client=httpx.AsyncClient())
    a, b = pool.add("a", "ka"), pool.add("b", "kb")
    assert a._limiters["data"] is b._limiters["data"]
    assert a._limiters["command"] is b._limiters["command"]
    assert a._ip_bucket is b._ip_bucket is not None
    assert a.headers["Authorization"] == "Bearer oxa_x" and a.headers["server-key"] == "ka"

    solo = AsyncServerPool(client=httpx.AsyncClient())          # no app key: limits are per server key
    c, d = solo.add("c", "kc"), solo.add("d", "kd")
    assert c._limiters["data"] is not d._limiters["data"]
    assert c._ip_bucket is d._ip_bucket is not None              # but the IP limit is shared


def test_pool_each_and_broadcast():
    async def main():
        pool, calls = pool_with({
            "ka": [(200, OK)],
            "kb": [(503, {"message": "Server is offline or unavailable", "Code": "OFFLINE"})],
        })
        pool.add("a", "ka")
        pool.add("b", "kb")
        results = await pool.run_command_on_all("announce Maintenance at 6pm")
        assert results["a"]["Status"] == "Succeeded"
        assert isinstance(results["b"], oxrpy.ServerOfflineError)
        await pool.aclose()

    asyncio.run(main())


def test_pool_add_remove_and_lookup():
    async def main():
        pool, _ = pool_with({"k": [(200, TOP)]})
        api = pool.add("guild-1", "k")
        assert pool["guild-1"] is api and "guild-1" in pool and len(pool) == 1
        with pytest.raises(ValueError):
            pool.add("guild-1", "k")
        await pool.remove("guild-1")
        assert "guild-1" not in pool
        with pytest.raises(ValueError):
            await pool.run_forever()          # no handlers
        await pool.aclose()

    asyncio.run(main())


def test_pool_save_dir(tmp_path):
    async def main():
        pool, _ = pool_with({"k": [(200, kills(1, 1)), (200, kills(2, 2))]})
        pool.add("guild/1", "k")

        @pool.on("Kill")
        def on_kill(server, kill):
            pool.stop()

        await asyncio.wait_for(pool.run_forever(save_dir=tmp_path), 5)
        saved = json.loads((tmp_path / "guild_1.json").read_text())
        assert saved["Cursor"] == 2
        await pool.aclose()

    asyncio.run(main())
