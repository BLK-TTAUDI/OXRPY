import json
import warnings
from urllib.parse import parse_qs, urlparse

import pytest
import requests

import oxrpy
from oxrpy import (
    AuthenticationError,
    BadRequestError,
    CommandFailedError,
    NotFoundError,
    OxfordAPI,
    RateLimitError,
    ServerOfflineError,
)


def make_response(status=200, body=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = b"" if body is None else json.dumps(body).encode()
    r.headers.update(headers or {})
    r.reason = {200: "OK", 304: "Not Modified"}.get(status, "Error")
    return r


class FakeSession(requests.Session):
    """Records requests and replays queued responses."""

    def __init__(self, *responses):
        super().__init__()
        self.queue = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None, **kw):
        merged = dict(self.headers)
        merged.update(headers or {})
        self.calls.append({"method": method, "url": url, "params": params or {}, "json": json,
                           "headers": merged, "timeout": timeout})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(*responses, **kw):
    session = FakeSession(*responses)
    kw.setdefault("rate_limit", "none")
    return OxfordAPI("sk_test", session=session, **kw), session


TOP = {"Online": True, "LastHeartbeat": 100, "NextHeartbeat": 101, "Cursor": 50,
       "Server": {"Name": "Test RP"}}


def test_version_and_exports():
    assert oxrpy.__version__ == "2.3.0"
    from oxrpy.oxrpy import OxfordAPI as Legacy  # 1.x import path
    assert Legacy is OxfordAPI


def test_requires_server_key():
    with pytest.raises(ValueError):
        OxfordAPI()


def test_headers_with_app_key():
    api, s = client(make_response(body=TOP), app_key="oxa_abc")
    api.get_server()
    h = s.calls[0]["headers"]
    assert h["server-key"] == "sk_test"
    assert h["Authorization"] == "Bearer oxa_abc"
    assert h["User-Agent"].startswith("oxrpy/2.3.0")


def test_no_authorization_header_without_app_key():
    api, s = client(make_response(body=TOP))
    api.get_server()
    assert "Authorization" not in s.calls[0]["headers"]


def test_global_key_and_server_id_warn():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        api = OxfordAPI("sk", global_key="oxa_x", server_id="abc", session=FakeSession())
    assert len([x for x in w if issubclass(x.category, DeprecationWarning)]) == 2
    assert api.session.headers["Authorization"] == "Bearer oxa_x"


def test_get_server_sends_a_parameter_for_new_shape():
    api, s = client(make_response(body=TOP))
    data = api.get_server()
    call = s.calls[0]
    assert call["url"] == "https://api.oxfd.re/v1/server"
    assert call["params"] == {"Players": "false"}
    assert data.online and data.cursor == 50 and data["Server"]["Name"] == "Test RP"


def test_get_server_data_params_and_case():
    api, s = client(make_response(body=dict(TOP, Players=[], Events=[]), headers={"ETag": 'W/"1"'}))
    data = api.get_server_data("players", "EVENTS", "Bans", since=88210, limit=200, offset=5,
                               audit_category=["Moderation", "Staff"], audit_user="@amy", audit_before=9)
    assert s.calls[0]["params"] == {
        "Players": "true", "Events": "true", "Bans": "true", "Since": "88210", "Limit": "200",
        "Offset": "5", "AuditBefore": "9", "AuditCategory": "Moderation,Staff", "AuditUser": "@amy",
    }
    assert data.etag == 'W/"1"'


def test_if_none_match_304_returns_none():
    api, s = client(make_response(status=304))
    assert api.get_server_data("Players", if_none_match='W/"1"') is None
    assert s.calls[0]["headers"]["If-None-Match"] == 'W/"1"'


def test_section_helpers():
    api, s = client(
        make_response(body=dict(TOP, Players=[{"UserId": 1}])),
        make_response(body=dict(TOP, Players=None, Online=False)),
        make_response(body=dict(TOP, KillLogs=None)),
    )
    assert api.get_players() == [{"UserId": 1}]
    assert api.get_players() is None           # offline
    assert api.get_killlogs(since=3) == []     # unreadable log -> []
    assert s.calls[2]["params"] == {"KillLogs": "true", "Since": "3"}


def test_iter_bans_pages():
    api, s = client(
        make_response(body=dict(TOP, Bans={"Total": 3, "Offset": 0, "List": [{"UserId": 1}, {"UserId": 2}]})),
        make_response(body=dict(TOP, Bans={"Total": 3, "Offset": 2, "List": [{"UserId": 3}]})),
    )
    assert [b["UserId"] for b in api.iter_bans(page_size=2)] == [1, 2, 3]
    assert s.calls[1]["params"]["Offset"] == "2"


def test_errors_map_to_exceptions():
    cases = [
        (400, {"message": "Unknown parameter: Player", "ValidParameters": ["Players"]}, BadRequestError),
        (401, {"message": "Missing required header: server-key"}, AuthenticationError),
        (403, {"message": "Invalid API key"}, AuthenticationError),
        (404, {"message": "No command with that id"}, NotFoundError),
    ]
    for status, body, exc in cases:
        api, _ = client(make_response(status, body))
        with pytest.raises(exc) as info:
            api.get_server_data("Players")
        assert info.value.status == status
        assert info.value.message == body["message"]
    api, _ = client(make_response(400, cases[0][1]))
    with pytest.raises(BadRequestError) as info:
        api.get_server_data("Player")
    assert info.value.valid_parameters == ["Players"]


def test_429_retries_with_retry_after(monkeypatch):
    sleeps = []
    monkeypatch.setattr(oxrpy.client.time, "sleep", sleeps.append)
    api, s = client(
        make_response(429, {"message": "Rate limit exceeded.", "retryAfter": 1}, {"Retry-After": "1"}),
        make_response(body=TOP),
    )
    assert api.get_server().online
    assert sleeps == [1.0] and len(s.calls) == 2


def test_429_gives_up(monkeypatch):
    monkeypatch.setattr(oxrpy.client.time, "sleep", lambda _: None)
    rl = make_response(429, {"message": "Rate limit exceeded.", "retryAfter": 2})
    api, _ = client(rl, rl, max_retries=1)
    with pytest.raises(RateLimitError) as info:
        api.get_server()
    assert info.value.retry_after == 2


def test_run_command():
    ok = {"CommandId": "c1", "Status": "Succeeded", "Code": "OK", "Message": "Kicked x"}
    api, s = client(make_response(body=ok))
    assert api.run_command(":kick x spam") == ok
    call = s.calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/v1/server/command")
    assert call["json"] == {"command": ":kick x spam"}
    assert call["timeout"] >= 15


def test_run_command_check_raises_on_failed():
    failed = {"CommandId": "c2", "Status": "Failed", "Code": "TARGET_NOT_FOUND", "Message": "No one matches x"}
    api, _ = client(make_response(body=failed))
    with pytest.raises(CommandFailedError) as info:
        api.run_command("kick x", check=True)
    assert info.value.code == "TARGET_NOT_FOUND" and info.value.command_id == "c2"


def test_run_commands_batch():
    res = [{"CommandId": "a", "Status": "Succeeded"}, {"CommandId": "b", "Status": "Succeeded"}]
    api, s = client(make_response(body=res))
    assert api.run_commands(["weather rain", "lockweather"]) == res
    assert s.calls[0]["json"] == {"commands": ["weather rain", "lockweather"]}
    with pytest.raises(ValueError):
        api.run_commands(["x"] * 11)
    with pytest.raises(ValueError):
        api.run_commands([])


def test_offline_command_raises():
    api, _ = client(make_response(503, {"message": "Server is offline or unavailable", "Code": "OFFLINE"}))
    with pytest.raises(ServerOfflineError) as info:
        api.run_command("announce hi")
    assert info.value.code == "OFFLINE"


def test_command_not_retried_on_timeout(monkeypatch):
    monkeypatch.setattr(oxrpy.client.time, "sleep", lambda _: None)
    api, s = client(requests.Timeout())
    with pytest.raises(oxrpy.OxfordAPIError):
        api.run_command("announce hi")
    assert len(s.calls) == 1


def test_get_retried_on_connection_error(monkeypatch):
    monkeypatch.setattr(oxrpy.client.time, "sleep", lambda _: None)
    api, s = client(requests.ConnectionError(), make_response(body=TOP))
    assert api.get_server().online and len(s.calls) == 2


def test_get_and_wait_for_command(monkeypatch):
    monkeypatch.setattr(oxrpy.client.time, "sleep", lambda _: None)
    api, s = client(make_response(body={"Id": "c1", "Status": "pending"}),
                    make_response(body={"Id": "c1", "Status": "succeeded", "Success": True}))
    assert api.wait_for_command("c1")["Status"] == "succeeded"
    assert s.calls[0]["url"].endswith("/v1/server/commands/c1")


def test_status_endpoint():
    api, s = client(make_response(body={"Status": "operational"}))
    assert api.get_status()["Status"] == "operational"
    assert s.calls[0]["url"] == "https://api.oxfd.re/status"


def test_legacy_managers():
    api, _ = client(make_response(body=dict(TOP, Players=[])),
                    make_response(body={"CommandId": "c", "Status": "Succeeded"}))
    assert api.servers.get_players() == []
    assert api.commands.execute_command("announce hi")["Status"] == "Succeeded"


def test_follower_dedupes_and_advances_cursor():
    first = dict(TOP, Cursor=12, Events=[{"Seq": 12, "Type": "B"}, {"Seq": 10, "Type": "A"}])
    # Events again includes seq 12 (another log overflowed), plus a new 13
    second = dict(TOP, Cursor=13, Events=[{"Seq": 13, "Type": "C"}, {"Seq": 12, "Type": "B"}])
    api, s = client(make_response(body=first), make_response(body=second))
    f = api.follow("events", sections=["Players"])
    _, new = f.poll()
    assert [e["Type"] for e in new["Events"]] == ["A", "B"]      # oldest first
    assert "Since" not in s.calls[0]["params"]
    _, new = f.poll()
    assert [e["Type"] for e in new["Events"]] == ["C"]
    assert s.calls[1]["params"]["Since"] == "12"
    assert s.calls[1]["params"]["Players"] == "true"
    assert f.cursor == 13


def test_follower_rejects_non_log_sections():
    api, _ = client()
    with pytest.raises(ValueError):
        api.follow("Players")


def test_token_bucket():
    from oxrpy import TokenBucket
    b = TokenBucket(rate=1000, capacity=2)
    assert b.try_acquire() and b.try_acquire()
    assert b.acquire(timeout=1)


def test_rate_limit_validation():
    with pytest.raises(ValueError):
        OxfordAPI("sk", rate_limit="fast", session=FakeSession())
    with pytest.raises(ValueError):
        OxfordAPI("sk", rate_limit=-1, session=FakeSession())
