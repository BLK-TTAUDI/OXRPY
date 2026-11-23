"""Tests for 2.1: command helpers, resilient following, event handlers and the async client."""

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
import requests

import oxrpy
from oxrpy import AsyncOxfordAPI, AuthenticationError, CommandFailedError, format_duration
from test_client import TOP, client, make_response

OK = {"CommandId": "c", "Status": "Succeeded", "Code": "OK", "Message": "Done"}


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Polling loops normally wait for the next heartbeat; make tests instant."""
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0)
    sleeps = []
    monkeypatch.setattr(oxrpy.follower.time, "sleep", sleeps.append)  # same module as client's
    return sleeps


def sent(*calls, **kw):
    """Run helper calls against a fake server and return the command text each one sent."""
    api, session = client(*[make_response(body=OK) for _ in calls], **kw)
    for call in calls:
        call(api)
    return [c["json"]["command"] for c in session.calls]


# ---------------------------------------------------------------- command helpers

def test_moderation_helpers():
    assert sent(
        lambda a: a.kick("dxrkrider", "Exploiting"),
        lambda a: a.kick(12345),
        lambda a: a.ban("m4tty_b", "Combat logging", "7d"),
        lambda a: a.ban("m4tty_b", "Fail RP 2"),            # reason ending in a number
        lambda a: a.ban("@m4tty_b"),
        lambda a: a.ban(99120344, duration=timedelta(hours=36)),
        lambda a: a.unban("m4tty_b"),
        lambda a: a.jail("x", 120),
        lambda a: a.wanted("team:Civilian", 0),
        lambda a: a.pm("all", "Server\nrestart  soon"),
        lambda a: a.resolve_modcall(4821),
    ) == [
        "kick dxrkrider Exploiting",
        "kick 12345",
        "ban m4tty_b Combat logging 7d",
        "ban m4tty_b Fail RP 2 permanent",
        "ban m4tty_b",
        "ban 99120344 1d12h",
        "unban m4tty_b",
        "jail x 120",
        "wanted team:Civilian 0",
        "pm all Server restart soon",
        "modcall resolve 4821",
    ]


def test_other_helpers():
    assert sent(
        lambda a: a.rank("amy_hx", "Senior Moderator"),
        lambda a: a.group_add(2938475610, "Undercover Police"),
        lambda a: a.set_team("x", "police"),
        lambda a: a.set_invincible("all", False),
        lambda a: a.remove_vehicle("RJ75 FLK"),
        lambda a: a.set_time(13.5),
        lambda a: a.set_weather("THUNDERSTORM"),
        lambda a: a.lock_weather(),
        lambda a: a.alert("Storm incoming", style="red"),
        lambda a: a.speed_limit(None),
        lambda a: a.speed_limit(60),
        lambda a: a.create_incident("ambulance", 2, -640, 1712.5, "Cyclist down on Abingdon Rd"),
        lambda a: a.radio("Police", "Suspect last seen on Cowley Rd"),
        lambda a: a.set_setting("TeamLimits", {"Police": 8, "Fire": 4}),
        lambda a: a.set_setting("Description", "Serious RP"),
        lambda a: a.respawn("nonadmins"),
        lambda a: a.teleport("nonadmins", "Officer_Smith"),
    ) == [
        "rank amy_hx Senior Moderator",
        "group add 2938475610 Undercover Police",
        "team x Police",
        "uninvincible all",
        "removevehicle RJ75FLK",
        "time 13.5",
        "weather thunderstorm",
        "lockweather",
        "redalert Storm incoming",
        "speedlimit off",
        "speedlimit 60",
        "incident create Ambulance 2 -640 1712.5 Cyclist down on Abingdon Rd",
        "radio Police Suspect last seen on Cowley Rd",
        'setting TeamLimits {"Police": 8, "Fire": 4}',
        'setting Description "Serious RP"',
        "load nonadmins",
        "tp nonadmins Officer_Smith",
    ]


@pytest.mark.parametrize("call", [
    lambda a: a.ban("x", "RDM", "7 days"),
    lambda a: a.ban("x", "RDM", "0m"),
    lambda a: a.ban("x", "a" * 201),
    lambda a: a.ban("two words"),
    lambda a: a.jail("x", 5),
    lambda a: a.wanted("x", 4),
    lambda a: a.wanted("x", 1.5),
    lambda a: a.set_team("x", "Swat"),
    lambda a: a.give("x", "rocket"),
    lambda a: a.set_time(25),
    lambda a: a.speed_limit(300),
    lambda a: a.create_incident("Civilian", 1, 0, 0, "x"),
    lambda a: a.create_incident("Police", 4, 0, 0, "x"),
    lambda a: a.announce("   "),
    lambda a: a.alert("x", style="blue"),
])
def test_helpers_reject_bad_arguments_before_sending(call):
    api, session = client()
    with pytest.raises(ValueError):
        call(api)
    assert session.calls == []


def test_helpers_raise_on_failed_by_default():
    failed = {"CommandId": "c", "Status": "Failed", "Code": "FORBIDDEN", "Message": "Can't kick staff"}
    api, _ = client(make_response(body=failed), make_response(body=failed))
    with pytest.raises(CommandFailedError) as info:
        api.kick("amy_hx")
    assert info.value.code == "FORBIDDEN"
    assert api.kick("amy_hx", check=False)["Status"] == "Failed"


def test_format_duration():
    assert format_duration("1D12H") == "1d12h"
    assert format_duration(None) == "permanent"
    assert format_duration("permanent") == "permanent"
    assert format_duration(90 * 60) == "1h30m"
    assert format_duration(timedelta(days=7)) == "7d"
    with pytest.raises(ValueError):
        format_duration(timedelta(days=4000))
    with pytest.raises(ValueError):
        format_duration("")


# ---------------------------------------------------------------- resilient following

def test_follow_keeps_going_after_errors(no_waiting):
    api, session = client(
        make_response(500, {"message": "Internal server error"}),
        make_response(429, {"message": "Rate limit exceeded.", "retryAfter": 5}),
        make_response(body=dict(TOP, Events=[{"Seq": 1, "Type": "Downed"}])),
        max_retries=0,
    )
    data, new = next(iter(api.follow("Events")))
    assert [e["Type"] for e in new["Events"]] == ["Downed"]
    assert no_waiting[:2] == [2.0, 5.0]       # backoff, then the API's Retry-After
    assert len(session.calls) == 3


def test_follow_network_errors_are_retried(no_waiting):
    api, _ = client(requests.ConnectionError(), make_response(body=dict(TOP, Events=[])), max_retries=0)
    data, new = next(iter(api.follow("Events")))
    assert new == {"Events": []}


def test_follow_stops_on_bad_key():
    api, _ = client(make_response(403, {"message": "Invalid API key"}))
    with pytest.raises(AuthenticationError):
        next(iter(api.follow("Events")))


def test_follow_without_retry_raises():
    api, _ = client(make_response(500, {"message": "Internal server error"}), max_retries=0)
    with pytest.raises(oxrpy.OxfordAPIError):
        next(api.follow("Events").iter(retry=False))


# ---------------------------------------------------------------- event handlers

def test_run_forever_dispatches_in_order_and_skips_backlog(monkeypatch):
    monkeypatch.setattr(oxrpy.follower, "error_delay", lambda exc, n: 0)
    old = dict(TOP, Cursor=5, KillLogs=[{"Seq": 5, "Type": "Kill"}], JoinLogs=[{"Seq": 4, "Type": "Join"}])
    new = dict(TOP, Cursor=9,
               KillLogs=[{"Seq": 8, "Type": "Kill", "Weapon": "G36C"}],
               JoinLogs=[{"Seq": 9, "Type": "Leave"}, {"Seq": 6, "Type": "Join"}],
               Players=[])
    api, session = client(make_response(body=old), make_response(500, {"message": "oops"}),
                          make_response(body=new), max_retries=0)
    seen, polls, errors = [], [], []

    @api.on("Kill")
    def on_kill(entry):
        seen.append(("kill", entry["Seq"]))

    @api.on("Join", "Leave")
    def on_join(entry):
        seen.append((entry["Type"].lower(), entry["Seq"]))

    @api.on("JoinLogs")
    def broken(entry):
        raise RuntimeError("a bad handler shouldn't stop the bot")

    api.on("error", errors.append)

    @api.on("poll")
    def on_poll(data):
        polls.append(data["Cursor"])
        if len(polls) == 2:
            api.stop()

    api.run_forever(sections=["Players"])

    assert seen == [("join", 6), ("kill", 8), ("leave", 9)]     # oldest first, backlog skipped
    assert polls == [5, 9]
    assert len(errors) == 1
    params = session.calls[0]["params"]
    assert params["KillLogs"] == params["JoinLogs"] == params["Players"] == "true"
    assert "Events" not in params
    assert session.calls[2]["params"]["Since"] == "5"
    assert api.cursor == 9


def test_event_types_go_to_events_log():
    api, session = client(make_response(body=dict(TOP, Events=[{"Seq": 1, "Type": "SpeedCamera"}])),
                          make_response(body=dict(TOP, Events=[{"Seq": 2, "Type": "SpeedCamera"}])))
    caught = []
    api.on("speedcamera", caught.append)
    api.on("poll", lambda d: api.stop() if caught else None)
    api.run_forever()
    assert session.calls[0]["params"] == {"Events": "true"}
    assert [e["Seq"] for e in caught] == [2]


def test_run_forever_needs_handlers():
    api, _ = client()
    with pytest.raises(ValueError):
        api.run_forever()


# ---------------------------------------------------------------- async client

def async_api(*responses, **kw):
    queue = list(responses)
    calls = []

    def handler(request):
        calls.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, body = item if isinstance(item, tuple) else (200, item)
        return httpx.Response(status, json=body)

    kw.setdefault("rate_limit", "none")
    api = AsyncOxfordAPI("sk_test", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)
    return api, calls


def test_async_reads_and_commands(monkeypatch):
    monkeypatch.setattr(oxrpy.aio.asyncio, "sleep", _instant)

    async def main():
        api, calls = async_api(dict(TOP, Players=[{"UserId": 1}]), OK,
                               (429, {"message": "Rate limit exceeded.", "retryAfter": 1}), OK,
                               {"Status": "operational"})
        async with api:
            assert await api.get_players() == [{"UserId": 1}]
            assert (await api.kick("dxrkrider", "Exploiting"))["Status"] == "Succeeded"
            assert (await api.run_command("announce hi"))["Status"] == "Succeeded"   # after one 429
            assert (await api.get_status())["Status"] == "operational"
        assert calls[0].headers["server-key"] == "sk_test"
        assert calls[0].url.params["Players"] == "true"
        assert json.loads(calls[1].content) == {"command": "kick dxrkrider Exploiting"}
        assert str(calls[4].url) == "https://api.oxfd.re/status"

    asyncio.run(main())


def test_async_errors_and_bans():
    async def main():
        api, _ = async_api((403, {"message": "Invalid API key"}),
                           dict(TOP, Bans={"Total": 2, "Offset": 0, "List": [{"UserId": 1}, {"UserId": 2}]}))
        with pytest.raises(AuthenticationError):
            await api.get_server()
        assert [b["UserId"] async for b in api.iter_bans()] == [1, 2]
        await api.aclose()

    asyncio.run(main())


def test_async_run_forever_with_async_handlers(monkeypatch):
    monkeypatch.setattr(oxrpy.aio.asyncio, "sleep", _instant)
    monkeypatch.setattr(oxrpy.follower, "error_delay", lambda exc, n: 0)

    async def main():
        api, _ = async_api(dict(TOP, Cursor=1, KillLogs=[{"Seq": 1, "Type": "Kill"}]),
                           (502, {"message": "Bad gateway"}),
                           dict(TOP, Cursor=2, KillLogs=[{"Seq": 2, "Type": "Kill"}]),
                           max_retries=0)
        kills = []

        @api.on("Kill")
        async def on_kill(entry):
            kills.append(entry["Seq"])
            api.stop()

        await asyncio.wait_for(api.run_forever(), timeout=5)
        assert kills == [2]
        await api.aclose()

    asyncio.run(main())


async def _instant(*_):
    return None
