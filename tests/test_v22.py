"""Tests for 2.2: typing, state events, staff/group sync, map helpers, catalogue cache, CLI,
examples and packaging."""

import asyncio
import py_compile
import re
import subprocess
import sys
from pathlib import Path

import pytest

import oxrpy
from oxrpy import map as oxmap
from oxrpy.__main__ import main as cli
from oxrpy.events import ServerWatcher
from oxrpy.sync import CommandWindow, plan_group_changes, plan_staff_changes
from test_client import TOP, client, make_response
from test_features import OK, async_api

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(oxrpy.follower._FollowerBase, "next_delay", lambda self, data=None, **kw: 0)
    sleeps = []
    monkeypatch.setattr(oxrpy.client.time, "sleep", sleeps.append)
    return sleeps


# ---------------------------------------------------------------- typing

def test_signature_stub_is_up_to_date():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_signatures.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_shared_method_is_typed_for_both_clients():
    stub = (ROOT / "oxrpy" / "_signatures.pyi").read_text(encoding="utf-8")
    sync_part, async_part = stub.split("class AsyncSignatures:")
    for name in ("get_players", "get_server_data", "kick", "ban", "plan_staff_sync", "get_catalogue"):
        assert f"    def {name}(" in sync_part
        assert f"    async def {name}(" in async_part
    assert "-> Optional[List[t.Player]]" in sync_part


def test_signature_classes_are_empty_at_runtime():
    # The real methods must come from BaseClient, not the typing-only classes.
    assert oxrpy.OxfordAPI.get_players is oxrpy._base.BaseClient.get_players
    assert not [n for n in vars(oxrpy._signatures.SyncSignatures) if not n.startswith("__")]


# ---------------------------------------------------------------- state events

def test_server_watcher():
    w = ServerWatcher()
    up = lambda started: dict(TOP, Online=True, Server={"StartedAt": started})
    down = dict(TOP, Online=False, Server={"StartedAt": 100})
    assert w.update(up(100)) == []                         # first poll: just records
    assert w.update(up(100)) == []
    assert w.update(down) == ["ServerOffline"]
    assert w.update(down) == []
    assert w.update(up(200)) == ["ServerOnline", "ServerRestart"]
    assert w.update(up(300)) == ["ServerRestart"]          # restarted between polls


def test_run_forever_fires_state_events_without_asking_for_logs():
    polls = [dict(TOP, Online=True, Server={"StartedAt": 1}),
             dict(TOP, Online=False, Server={"StartedAt": 1}),
             dict(TOP, Online=True, Server={"StartedAt": 2})]
    api, session = client(*[make_response(body=p) for p in polls])
    seen = []
    api.on("ServerOffline", lambda d: seen.append("offline"))
    api.on("ServerOnline", lambda d: seen.append("online"))

    @api.on("ServerRestart")
    def restarted(data):
        seen.append("restart")
        api.stop()

    api.run_forever()
    assert seen == ["offline", "online", "restart"]
    assert session.calls[0]["params"] == {"Players": "false"}   # no logs requested


# ---------------------------------------------------------------- staff and group sync

STAFF = {
    "OwnerId": 1,
    "Staff": [
        {"UserId": 10, "RankId": "mod", "Rank": "Mod"},
        {"UserId": 11, "RankId": "admin", "Rank": "Admin"},
        {"UserId": 12, "RankId": "mod", "Rank": "Mod"},
    ],
    "Ranks": [
        {"Id": "admin", "Name": "Admin"},
        {"Id": "senior-mod", "Name": "Senior Moderator"},
        {"Id": "mod", "Name": "Mod"},
    ],
}


def test_plan_staff_changes():
    desired = {10: "mod", "11": "Senior Moderator", 13: "Admin", 12: None, 1: "Mod"}
    assert plan_staff_changes(STAFF, desired) == [
        "unrank 12",
        "rank 11 senior-mod",
        "rank 13 admin",
    ]                                                   # 10 unchanged, owner (1) untouched
    assert plan_staff_changes(STAFF, {10: "Mod"}, remove_others=True) == ["unrank 11", "unrank 12"]
    assert plan_staff_changes(STAFF, {10: "MOD", 11: "admin", 12: "mod"}) == []


def test_plan_staff_changes_rejects_names_and_unknown_ranks():
    with pytest.raises(ValueError, match="user IDs"):
        plan_staff_changes(STAFF, {"kieran_rd": "Mod"})
    with pytest.raises(ValueError, match="No rank called 'Overlord'.*Senior Moderator"):
        plan_staff_changes(STAFF, {10: "Overlord"})


def test_plan_group_changes():
    groups = [{"Id": "cid", "Name": "CID", "Members": [10, 11]}, {"Id": "a1", "Name": "Traffic", "Members": []}]
    assert plan_group_changes(groups, "cid", [11, 12]) == ["group add 12 cid", "group remove 10 cid"]
    assert plan_group_changes(groups, "CID", [11, 12], remove_others=False) == ["group add 12 cid"]
    with pytest.raises(ValueError, match="CID, Traffic"):
        plan_group_changes(groups, "SWAT", [1])


def test_command_window():
    w = CommandWindow()
    assert w.wait_time(10, now=0) == 0
    w.record(10, now=0)
    assert w.wait_time(5, now=1) == 0
    w.record(5, now=1)
    assert w.wait_time(1, now=2) == pytest.approx(8.25)   # oldest frees up at t=10
    assert w.wait_time(1, now=10.5) == 0


def test_run_many_batches_and_paces(no_waiting):
    commands = [f"announce {i}" for i in range(23)]
    batch = lambda n: make_response(body=[OK] * n)
    api, session = client(batch(10), batch(10), batch(3))
    results = api.run_many(commands)
    assert len(results) == 23
    assert [len(c["json"]["commands"]) for c in session.calls] == [10, 10, 3]
    assert len(no_waiting) == 2 and no_waiting[0] > 9        # waited for the game's window


def test_sync_staff_end_to_end():
    api, session = client(make_response(body=dict(TOP, Staff=STAFF)),
                          make_response(body=[OK, OK]))
    done = api.sync_staff({11: "Senior Moderator", 13: "Mod"})
    assert [cmd for cmd, _ in done] == ["rank 11 senior-mod", "rank 13 mod"]
    assert session.calls[1]["json"] == {"commands": ["rank 11 senior-mod", "rank 13 mod"]}


def test_sync_with_nothing_to_do_sends_no_commands():
    api, session = client(make_response(body=dict(TOP, Staff=STAFF)))
    assert api.sync_staff({10: "Mod"}) == []
    assert len(session.calls) == 1


def test_async_sync_group(monkeypatch):
    async def main():
        groups = [{"Id": "cid", "Name": "CID", "Members": [10]}]
        api, calls = async_api(dict(TOP, Groups=groups), [OK])
        done = await api.sync_group("CID", [10, 20])
        assert done == [("group add 20 cid", OK)]
        await api.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------- map

def test_map_corners_and_round_trip():
    assert oxmap.to_pixels([-6700, 50, -2500]) == (0, 0)
    assert oxmap.to_pixels((1450, 3800)) == (8151, 6301)
    px, py = oxmap.to_pixels([512.4, 14.2, -88.0], width=1630, height=1260)
    x, z = oxmap.from_pixels(px, py, width=1630, height=1260)
    assert x == pytest.approx(512.4) and z == pytest.approx(-88.0)
    assert oxmap.to_pixels([-9000, 0, 0], clamp=True)[0] == 0
    assert oxmap.on_map([0, 0, 0]) and not oxmap.on_map([5000, 0, 0])


def test_map_distance_and_nearest():
    assert oxmap.distance([0, 100, 0], [3, 0, 4]) == 5
    places = [{"Name": "Bank", "Position": [412, 10, 1238]}, {"Name": "Station", "Position": [210, 6, 905]},
              {"Name": "Nowhere", "Position": None}]
    assert oxmap.nearest([400, 0, 1200], places)["Name"] == "Bank"
    with pytest.raises(ValueError):
        oxmap.to_pixels(None)


# ---------------------------------------------------------------- catalogue cache

def test_catalogue_is_cached():
    cat = {"Version": "25573"}
    api, session = client(make_response(body=dict(TOP, Catalogue=cat)),
                          make_response(body=dict(TOP, Catalogue=cat)))
    assert api.get_catalogue() == cat
    assert api.get_catalogue() == cat
    assert len(session.calls) == 1
    api.get_catalogue(refresh=True)
    assert len(session.calls) == 2


def test_async_catalogue_is_cached():
    async def main():
        api, calls = async_api(dict(TOP, Catalogue={"Version": "1"}))
        assert await api.get_catalogue() == {"Version": "1"}
        assert await api.get_catalogue() == {"Version": "1"}
        assert len(calls) == 1
        await api.aclose()

    asyncio.run(main())


# ---------------------------------------------------------------- CLI

def test_cli_status(monkeypatch, capsys):
    monkeypatch.setattr(oxrpy.OxfordAPI, "get_status", lambda self: {
        "Status": "operational", "UptimeSeconds": 90061, "LastHour": {"P50Ms": 4, "P95Ms": 19},
        "Uptime": {"Windows": {"24h": 100}}})
    assert cli(["status"]) == 0
    out = capsys.readouterr().out
    assert "operational" in out and "1d 1h 1m" in out and "24h 100%" in out


def test_cli_players_needs_key(monkeypatch):
    monkeypatch.delenv("OXFD_SERVER_KEY", raising=False)
    with pytest.raises(SystemExit, match="OXFD_SERVER_KEY"):
        cli(["players"])


def test_cli_players(monkeypatch, capsys):
    monkeypatch.setenv("OXFD_SERVER_KEY", "k")
    monkeypatch.setattr(oxrpy.OxfordAPI, "get_players", lambda self: [
        {"Username": "kieran_rd", "Team": "Police", "Location": {"Area": "Oxford Bank"}, "Rank": "Mod"},
        {"Username": "amy", "Team": "Civilian", "Location": None}])
    assert cli(["players"]) == 0
    out = capsys.readouterr().out
    assert "kieran_rd" in out and "[Mod]" in out and "2 players" in out


def test_cli_reports_api_errors(monkeypatch, capsys):
    def fail(self):
        raise oxrpy.AuthenticationError("Invalid API key", status=403)

    monkeypatch.setattr(oxrpy.OxfordAPI, "get_server", fail)
    assert cli(["--key", "bad", "server"]) == 1
    assert "Invalid API key" in capsys.readouterr().err


# ---------------------------------------------------------------- examples, docs and packaging

@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*.py")), ids=lambda p: p.name)
def test_examples_compile(path):
    py_compile.compile(str(path), doraise=True)


def test_readme_links_are_absolute():
    """PyPI shows the README on its own, so links like (CHANGELOG.md) 404 there."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)]+)\)", readme)
    relative = [link for link in links if not link.startswith(("http://", "https://", "#"))]
    assert relative == []


def test_tests_are_not_shipped_in_the_source_package():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "prune tests" in manifest


def test_readme_sections_for_the_docs_site_are_intact():
    """The docs site (a separate repo) pulls each guide page from a marked README section.
    Every section that's started must be ended, once, in order."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    starts = re.findall(r"<!-- --8<-- \[start:([a-z-]+)\] -->", readme)
    ends = re.findall(r"<!-- --8<-- \[end:([a-z-]+)\] -->", readme)
    assert starts and starts == ends and len(set(starts)) == len(starts)
    for needed in ("intro", "getting-started", "reading-data", "events", "commands", "async",
                   "many-servers", "map", "cli", "examples"):
        assert needed in starts
