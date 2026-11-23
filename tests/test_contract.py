"""The shared contract: fixtures/contract.json and the sample responses next to it.

oxrpy-js runs the same cases against its own code (with an exact copy of fixtures/), so if the
two wrappers ever start behaving differently, one of the suites fails.
"""

import json
from pathlib import Path

import pytest

import oxrpy
from oxrpy import errors, lookup
from test_client import FakeSession, make_response

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CONTRACT = json.loads((FIXTURES / "contract.json").read_text(encoding="utf-8"))
FULL = json.loads((FIXTURES / "server_full.json").read_text(encoding="utf-8"))
OFFLINE = json.loads((FIXTURES / "server_offline.json").read_text(encoding="utf-8"))
OK = {"CommandId": "c", "Status": "Succeeded", "Code": "OK", "Message": "Done"}
LOGS = ("KillLogs", "ModCalls", "RadioCalls", "JoinLogs", "Events", "CommandLogs", "CommandResults", "Shots")


def client(*responses):
    session = FakeSession(*responses)
    return oxrpy.OxfordAPI("sk_test", session=session, rate_limit="none", max_retries=0), session


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0)


@pytest.mark.parametrize("case", CONTRACT["commands"], ids=lambda c: c["text"])
def test_command_text(case):
    api, session = client(make_response(body=OK))
    getattr(api, case["py"])(*case["args"])
    assert session.calls[0]["json"] == {"command": case["text"]}


@pytest.mark.parametrize("case", CONTRACT["invalid_commands"], ids=lambda c: f'{c["py"]}{c["args"]}')
def test_invalid_commands_are_refused_before_sending(case):
    api, session = client()
    with pytest.raises((ValueError, TypeError)):
        getattr(api, case["py"])(*case["args"])
    assert session.calls == []


@pytest.mark.parametrize("case", CONTRACT["find_player"], ids=lambda c: c["why"])
def test_find_player(case):
    if "ambiguous" in case:
        with pytest.raises(lookup.AmbiguousMatchError) as info:
            lookup.find_player(FULL["Players"], case["query"])
        assert sorted(p["Username"] for p in info.value.matches) == sorted(case["ambiguous"])
    else:
        found = lookup.find_player(FULL["Players"], case["query"])
        assert (found or {}).get("UserId") == case["user_id"]


@pytest.mark.parametrize("case", CONTRACT["find_vehicle"], ids=lambda c: c["why"])
def test_find_vehicle(case):
    assert lookup.find_vehicle(FULL["Vehicles"], case["query"], FULL["Players"])["Plate"] == case["plate"]


def test_team_and_staff_lookups():
    team = CONTRACT["players_on_team"]
    assert [p["Username"] for p in lookup.players_on_team(FULL["Players"], team["team"])] == team["usernames"]
    assert [p["Username"] for p in lookup.staff_online(FULL["Players"])] == CONTRACT["staff_online"]["usernames"]


def test_dispatch_order():
    top = {k: v for k, v in FULL.items() if k not in LOGS}
    second = {**top, **CONTRACT["dispatch"]["second_poll"]}
    api, _ = client(make_response(body=FULL), make_response(body=second))
    fired = []
    for key in ("Kill", "Join", "Leave", "SpeedCamera"):
        api.on(key, lambda entry: fired.append(f'{entry["Type"]}:{entry["Seq"]}'))
    api.on("poll", lambda data: api.stop() if data["Cursor"] == CONTRACT["dispatch"]["second_poll"]["Cursor"] else None)
    api.run_forever()
    assert fired == CONTRACT["dispatch"]["order"]


@pytest.mark.parametrize("case", CONTRACT["errors"], ids=lambda c: f'{c["status"]} {c["body"]["message"][:30]}')
def test_errors(case):
    api, _ = client(make_response(case["status"], case["body"]))
    with pytest.raises(oxrpy.OxfordAPIError) as info:
        api.get_server_data("Players")
    assert type(info.value).__name__ == case["type"]
    assert type(info.value) is getattr(errors, case["type"])
    if "hint" in case:
        assert info.value.hint == case["hint"]
    else:
        assert case["hint_contains"].lower() in (info.value.hint or "").lower()


def test_failed_command():
    failed = CONTRACT["failed_command"]
    api, _ = client(make_response(body=failed["result"]))
    with pytest.raises(oxrpy.CommandFailedError) as info:
        api.run_command("kick x", check=True)
    assert info.value.code == failed["result"]["Code"]
    assert failed["hint_contains"] in info.value.hint


def test_latest_keeps_live_sections_only():
    api, _ = client(make_response(body=FULL))
    api.get_server_data(*[k for k in FULL if k not in ("Online", "LastHeartbeat", "NextHeartbeat", "Cursor", "Server")])
    for section in CONTRACT["latest"]["kept"]:
        assert section in api.latest, section
    for section in CONTRACT["latest"]["not_kept"]:
        assert section not in api.latest, section


def test_offline_server():
    api, _ = client(make_response(body=OFFLINE))
    data = api.get_server_data("Players", "Staff")
    assert data["Players"] is CONTRACT["offline"]["players"]
    assert api.latest.online is CONTRACT["offline"]["online"]
    assert len(data["Staff"]["Staff"]) == CONTRACT["offline"]["staff_count"]
