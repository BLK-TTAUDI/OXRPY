"""Security behaviour: where the API key can and can't end up."""

import asyncio

import httpx
import pytest
import requests

import oxrpy
from oxrpy import OxfordAPI
from oxrpy.pool import _file_name
from test_client import TOP, FakeSession, client, make_response


def test_redirects_are_not_followed_and_raise():
    api, session = client(make_response(302, None, {"Location": "https://evil.example/steal"}))
    with pytest.raises(oxrpy.OxfordAPIError, match="redirect"):
        api.get_server()
    assert len(session.calls) == 1                      # never went to evil.example


def test_requests_is_told_not_to_follow_redirects(monkeypatch):
    seen = {}

    def fake_request(self, method, url, **kwargs):
        seen.update(kwargs)
        return make_response(body=TOP)

    monkeypatch.setattr(requests.Session, "request", fake_request)
    OxfordAPI("sk", rate_limit="none").get_server()
    assert seen["allow_redirects"] is False
    assert seen["headers"]["server-key"] == "sk"


def test_users_own_session_is_never_given_the_key():
    mine = requests.Session()
    before = dict(mine.headers)
    api = OxfordAPI("secret-key", app_key="oxa_secret", session=mine)
    assert dict(mine.headers) == before
    assert "secret-key" not in repr(api) and "secret-key" not in str(vars(mine))


def test_async_client_never_follows_redirects():
    async def main():
        hits = []

        def handler(request):
            hits.append(str(request.url))
            return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

        own = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
        api = oxrpy.AsyncOxfordAPI("sk", client=own, rate_limit="none")
        with pytest.raises(oxrpy.OxfordAPIError, match="redirect"):
            await api.get_server()
        assert hits == ["https://api.oxfd.re/v1/server?Players=false"]
        await own.aclose()

    asyncio.run(main())


@pytest.mark.parametrize("url", ["http://api.oxfd.re/v1", "ftp://x", "api.oxfd.re/v1", "http://10.0.0.5/v1"])
def test_key_is_only_sent_over_https(url):
    with pytest.raises(ValueError, match="https"):
        OxfordAPI("sk", base_url=url, session=FakeSession())


def test_plain_http_is_allowed_for_local_testing():
    assert OxfordAPI("sk", base_url="http://localhost:8080/v1", session=FakeSession()).base_url == \
        "http://localhost:8080/v1"


def test_retry_after_is_capped(monkeypatch):
    sleeps = []
    monkeypatch.setattr(oxrpy.client.time, "sleep", sleeps.append)
    api, _ = client(make_response(429, {"message": "slow down"}, {"Retry-After": "999999999"}),
                    make_response(body=TOP))
    api.get_server()
    assert sleeps == [oxrpy._base.MAX_RETRY_WAIT]


def test_command_id_cant_change_the_path():
    api, session = client(make_response(body={"Status": "succeeded"}))
    api.get_command("../../server?Settings=true")
    assert session.calls[0]["url"] == \
        "https://api.oxfd.re/v1/server/commands/..%2F..%2Fserver%3FSettings%3Dtrue"


def test_pool_file_names_never_collide():
    names = ["a/b", "a_b", "a\b", "..", "guild-1", "x" * 300]
    files = [_file_name(n) for n in names]
    assert len(set(files)) == len(files)
    assert all("/" not in f and "\\" not in f and f not in (".", "..") for f in files)
    assert _file_name("guild-1") == "guild-1"           # ordinary names are kept as they are
