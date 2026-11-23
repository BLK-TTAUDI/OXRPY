"""Tests for 2.4: error hints, request hooks and rate limit status, api.latest, lookups,
update_setting, iter_audit, adaptive polling and typed handlers."""

import asyncio
import json
import time
from pathlib import Path

import pytest
import requests

import oxrpy
from oxrpy import lookup
from oxrpy.errors import AuthenticationError, BadRequestError, CommandFailedError, OxfordAPIError
from oxrpy.follower import LogFollower
from oxrpy.lookup import AmbiguousMatchError
from test_client import TOP, client, make_response
from test_features import OK, async_api

ROOT = Path(__file__).resolve().parent.parent

PLAYERS = [
    {"UserId": 81234401, "Username": "kieran_rd", "DisplayName": "Kieran", "Team": "Police", "Rank": "Mod"},
    {"UserId": 99120344, "Username": "dxrkrider", "DisplayName": "Dark", "Team": "Civilian", "Rank": None},
    {"UserId": 99120377, "Username": "kierstan", "DisplayName": "K", "Team": "civilian", "Rank": None},
    {"UserId": 55, "Username": "ownerman", "DisplayName": "Boss", "Team": "Civilian", "Rank": "Owner"},
]
VEHICLES = [
    {"Plate": "RJ75 FLK", "OwnerId": 99120344, "Model": "Strassen Solo"},
    {"Plate": "OX24 KRD", "OwnerId": 81234401, "Model": "Strassen Reuter"},
]


# ---------------------------------------------------------------- error hints

def test_errors_carry_hints_without_changing_the_message():
    api, _ = client(make_response(403, {"message": "Invalid API key"}))
    with pytest.raises(AuthenticationError) as info:
        api.get_server()
    assert info.value.message == "Invalid API key"
    assert "regenerated" in info.value.hint
    assert str(info.value).startswith("403: Invalid API key (hint: ")


def test_bad_section_name_suggests_the_right_one():
    api, _ = client(make_response(400, {"message": "Unknown parameter: Player",
                                        "ValidParameters": ["Players", "Vehicles", "Since"]}))
    with pytest.raises(BadRequestError) as info:
        api.get_server_data("Player")
    assert info.value.hint == "Did you mean 'Players'?"


def test_failed_commands_get_hints_by_code():
    api, _ = client(make_response(body={"CommandId": "c", "Status": "Failed", "Code": "PACKAGE_REQUIRED",
                                        "Message": "RoleplayKit only"}))
    with pytest.raises(CommandFailedError) as info:
        api.give("all", "megaphone")
    assert "package" in info.value.hint.lower()
    assert OxfordAPIError("Something odd").hint is None


# ---------------------------------------------------------------- request hooks and rate limits

def test_on_request_sees_every_attempt_and_rate_limits_are_recorded(monkeypatch):
    monkeypatch.setattr(oxrpy.client.time, "sleep", lambda s: None)
    api, _ = client(
        make_response(429, {"message": "slow down", "retryAfter": 1}, {"Retry-After": "1"}),
        make_response(body=TOP, headers={"X-RateLimit-Limit": "1", "X-RateLimit-Remaining": "1",
                                         "X-RateLimit-Reset": "0"}),
        requests.ConnectionError("down"),
        requests.ConnectionError("still down"),
        max_retries=1,
    )
    seen = []
    api.on_request(seen.append)

    @api.on_request
    def broken(info):
        raise RuntimeError("a bad hook must not break requests")

    api.get_server()
    with pytest.raises(OxfordAPIError):
        api.get_command("abc")                 # network error, retried once, then raised
    assert [(i.status, i.attempt, i.will_retry) for i in seen] == [
        (429, 0, True), (200, 1, False), (None, 0, True), (None, 1, False)]
    assert seen[1].path == "/server" and seen[1].rate_limit == {"Limit": 1.0, "Remaining": 1.0, "Reset": 0.0}
    assert isinstance(seen[2].error, requests.ConnectionError)
    status = api.rate_limit_status
    assert status["data"]["Remaining"] == 1.0 and "At" in status["data"]
    assert "server-key" not in repr(seen)


# ---------------------------------------------------------------- api.latest

def test_latest_keeps_live_sections_but_not_logs():
    api, _ = client(make_response(body=dict(TOP, Players=PLAYERS, Events=[{"Seq": 1}], Bans={"Total": 0})))
    assert api.latest.players is None and api.latest.age("Players") is None
    api.get_server_data("Players", "Events", "Bans")
    assert api.latest.players == PLAYERS
    assert api.latest.online is True and api.latest.server["Name"] == "Test RP"
    assert api.latest.age("Players") < 1 and api.latest.is_fresh("Players", 5)
    assert "Events" not in api.latest and "Bans" not in api.latest
    assert api.latest.sections == ["Cursor", "LastHeartbeat", "NextHeartbeat", "Online", "Players", "Server"]


def test_latest_shows_offline():
    api, _ = client(make_response(body=dict(TOP, Online=False, Players=None)))
    api.get_players()
    assert api.latest.online is False and api.latest.players is None


# ---------------------------------------------------------------- lookups

def test_find_player_follows_oxfords_rules():
    assert lookup.find_player(PLAYERS, "KIERAN_RD")["UserId"] == 81234401      # username, any case
    assert lookup.find_player(PLAYERS, "boss")["Username"] == "ownerman"       # display name
    assert lookup.find_player(PLAYERS, 99120344)["Username"] == "dxrkrider"   # user ID
    assert lookup.find_player(PLAYERS, "@dxrk")["UserId"] == 99120344         # part of a name, @ ignored
    assert lookup.find_player(PLAYERS, "nobody") is None
    assert lookup.find_player(None, "x") is None                               # offline
    with pytest.raises(AmbiguousMatchError) as info:
        lookup.find_player(PLAYERS, "kier")                                    # kieran_rd and kierstan
    assert {p["Username"] for p in info.value.matches} == {"kieran_rd", "kierstan"}
    assert "matches 2 players" in str(info.value)


def test_team_staff_and_vehicle_lookups():
    assert [p["Username"] for p in lookup.players_on_team(PLAYERS, "CIVILIAN")] == ["dxrkrider", "kierstan", "ownerman"]
    assert [p["Username"] for p in lookup.staff_online(PLAYERS)] == ["kieran_rd", "ownerman"]
    assert lookup.find_vehicle(VEHICLES, "rj75flk")["OwnerId"] == 99120344
    assert lookup.find_vehicle(VEHICLES, "kieran_rd", PLAYERS)["Plate"] == "OX24 KRD"
    assert lookup.find_vehicle(VEHICLES, 99120344)["Plate"] == "RJ75 FLK"
    assert lookup.find_vehicle(VEHICLES, "ownerman", PLAYERS) is None


def test_client_lookups_use_latest_when_fresh():
    api, session = client(make_response(body=dict(TOP, Players=PLAYERS)),
                          make_response(body=dict(TOP, Players=PLAYERS[:1])))
    assert api.find_player("dxrkrider")["UserId"] == 99120344         # fetched
    assert len(api.staff_online()) == 2                               # answered from api.latest
    assert len(session.calls) == 1
    assert api.find_player("dxrkrider", max_age=0) is None             # forced fetch: they've left
    assert len(session.calls) == 2


def test_find_vehicle_fetches_both_sections():
    api, session = client(make_response(body=dict(TOP, Players=PLAYERS, Vehicles=VEHICLES)))
    assert api.find_vehicle("kieran_rd")["Plate"] == "OX24 KRD"
    assert session.calls[0]["params"] == {"Vehicles": "true", "Players": "true"}


# ---------------------------------------------------------------- update_setting and iter_audit

SETTINGS = {"TeamLimits": {"Police": 8, "Fire": 4}, "Tags": ["UK"], "AdminWebhook": "(set)", "MaxPlayers": 36}


def test_update_setting_sends_the_whole_new_value():
    api, session = client(make_response(body=dict(TOP, Settings=SETTINGS)), make_response(body=OK),
                          make_response(body=dict(TOP, Settings=SETTINGS)), make_response(body=OK))
    api.update_setting("Tags", lambda tags: tags + ["Serious"])                # returns a new value
    assert session.calls[1]["json"] == {"command": 'setting Tags ["UK", "Serious"]'}
    api.update_setting("TeamLimits", lambda limits: limits.update(Police=10))  # changes in place
    assert session.calls[3]["json"] == {"command": 'setting TeamLimits {"Police": 10, "Fire": 4}'}
    assert SETTINGS["TeamLimits"]["Police"] == 8                              # the original wasn't touched


def test_update_setting_skips_no_change_and_refuses_unsafe_ones():
    api, session = client(*[make_response(body=dict(TOP, Settings=SETTINGS)) for _ in range(4)])
    assert api.update_setting("MaxPlayers", 36) is None
    assert api.update_setting("Tags", lambda tags: None) is None              # mutated nothing
    with pytest.raises(KeyError, match="Did you mean 'TeamLimits'"):
        api.update_setting("teamlimits", {})
    with pytest.raises(ValueError, match="webhook"):
        api.update_setting("AdminWebhook", "https://x")
    assert all("command" not in (c["json"] or {}) for c in session.calls)     # nothing was sent


def test_iter_audit_pages_through_everything():
    pages = [
        {"Entries": [{"Number": 5}, {"Number": 4}], "Next": 4, "Total": 5},
        {"Entries": [{"Number": 3}], "Next": 3, "Total": 5},
        {"Entries": [{"Number": 2}, {"Number": 1}], "Next": None, "Total": 5},
    ]
    api, session = client(*[make_response(body=dict(TOP, Audit=p)) for p in pages])
    assert [e["Number"] for e in api.iter_audit(category="Moderation", page_size=2)] == [5, 4, 3, 2, 1]
    assert [c["params"].get("AuditBefore") for c in session.calls] == [None, "4", "3"]
    assert session.calls[0]["params"]["AuditCategory"] == "Moderation"


def test_async_update_setting_and_iter_audit():
    async def main():
        api, calls = async_api(dict(TOP, Settings=SETTINGS), OK,
                               dict(TOP, Audit={"Entries": [{"Number": 1}], "Next": None}))
        result = await api.update_setting("Tags", lambda tags: tags + ["VC"])
        assert result["Status"] == "Succeeded"
        assert json.loads(calls[1].content) == {"command": 'setting Tags ["UK", "VC"]'}
        assert [e["Number"] async for e in api.iter_audit()] == [1]
        await api.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------- adaptive polling

def _beat(players=10):
    return dict(TOP, NextHeartbeat=time.time(), Server={"CurrentPlayers": players})


def test_adaptive_polling_backs_off_when_quiet_and_resets_on_activity():
    api, _ = client()
    f = LogFollower(api, ["Events"], adaptive=True, max_idle=5)
    assert f.next_delay(_beat()) == pytest.approx(1.0, abs=0.1)        # nothing seen yet: every beat
    delays = []
    for _ in range(6):
        f._process(dict(_beat(), Events=[]))
        delays.append(round(f.next_delay(), 2))
    assert delays == [1.5, 2.25, 3.38, 5.0, 5.0, 5.0]
    f._process(dict(_beat(), Events=[{"Seq": 1}]))                     # something happened
    assert f.next_delay() == pytest.approx(1.0, abs=0.1)
    assert f.next_delay(_beat(players=0)) == 5.0                        # empty server
    plain = LogFollower(api, ["Events"])                                 # off by default
    plain._process(dict(_beat(players=0), Events=[]))
    assert plain.next_delay() == pytest.approx(1.0, abs=0.1)


def test_pool_polls_adaptively_by_default():
    import inspect
    sig = inspect.signature(oxrpy.AsyncServerPool.run_forever)
    assert sig.parameters["adaptive"].default is True and sig.parameters["max_idle"].default == 5.0


# ---------------------------------------------------------------- typed handlers

def test_handler_overloads_are_in_the_stub():
    stub = (ROOT / "oxrpy" / "_signatures.pyi").read_text(encoding="utf-8")
    for key, kind in (('"Kill", "KillLogs"', "t.KillLog"), ('"Join", "Leave", "JoinLogs"', "t.JoinLog"),
                      ('"error"', "OxfordAPIError")):
        assert f"def on(self, key: Literal[{key}], /) -> Callable[[Callable[[{kind}], Any]]" in stub
    assert stub.count("    @overload\n    def on(self, *keys: Any) -> Any:") == 2   # sync and async
