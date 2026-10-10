"""Exercise the recorded protocol using synthetic, secret-free responses."""

import json
from unittest.mock import AsyncMock

import aiohttp
import pytest
from yarl import URL

from custom_components.watersmart.api import (
    CHART_PATH,
    HOME_PATH,
    LOGIN_PATH,
    USAGE_PATH,
    AccountMismatchError,
    AuthenticationError,
    LoginParser,
    WaterSmartClient,
    WaterSmartError,
    account_from_html,
    normalize_url,
    parse_chart,
)

HOME = """<div id="account-navigation"><span>
<div class="title">Account Number</div><div><var>0012345</var></div>
</span></div>"""
LOGIN = '<input value="fresh-token" name="token"><input name="password">'
CHART = {"data": {"series": [{"read_datetime": 3600, "gallons": 2.5}]}}


def test_login_token_and_account():
    parser = LoginParser()
    parser.feed(LOGIN)
    assert parser.token == "fresh-token"
    assert parser.is_login
    assert account_from_html(HOME) == "0012345"


@pytest.mark.parametrize(
    "html",
    [
        '<section id="account-navigation"><b>Account&nbsp;Number</b>'
        '<div class="value"><var data-id="account"><span>0012345</span></var></div>'
        "</section>",
        '<div id="account-navigation"><span>Account Number:</span>'
        '<span class="value">0012345</span></div>',
        "<main><p>Account Number</p><p>0012345</p></main>",
    ],
)
def test_account_parser_accepts_layout_variations(html):
    assert account_from_html(html) == "0012345"


def test_account_parser_rejects_ambiguous_identity():
    with pytest.raises(WaterSmartError, match="multiple"):
        account_from_html("<main>Account Number 0012345 Account Number 9999999</main>")


def test_account_parser_does_not_use_form_labels_or_script_text():
    with pytest.raises(WaterSmartError, match="did not identify"):
        account_from_html(
            "<script>Account Number 9999999</script>"
            "<label>Account number</label><label>Zip code</label>"
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://milpitas.watersmart.com",
        "https://watersmart.com.attacker.org",
        "https://evilwatersmart.com",
        "https://a.watersmart.com/path",
        "https://user:secret@a.watersmart.com",
        "https://a.watersmart.com:8443",
    ],
)
def test_reject_unsafe_portal(url):
    with pytest.raises(ValueError):
        normalize_url(url)


def test_chart_combines_repeated_hours_sorts_and_skips_missing():
    payload = {
        "data": {
            "series": [
                {"read_datetime": 7200, "gallons": 0},
                {"read_datetime": 3600, "gallons": 3},
                {"read_datetime": 3600, "gallons": 4},
                {"read_datetime": 10800, "gallons": None},
            ]
        }
    }
    assert list(parse_chart(payload).items()) == [(3600, 7), (7200, 0)]


@pytest.mark.parametrize(
    "row",
    [
        {"read_datetime": 3600001, "gallons": 1},
        {"read_datetime": 3600, "gallons": -1},
        {"read_datetime": 3600, "gallons": float("nan")},
        {"read_datetime": 3600, "gallons": float("inf")},
        {"read_datetime": 3600.5, "gallons": 1},
        {"read_datetime": True, "gallons": 1},
    ],
)
def test_chart_rejects_bad_readings(row):
    with pytest.raises(WaterSmartError):
        parse_chart({"data": {"series": [row]}})


async def test_login_uses_fresh_token_and_cookie_session():
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(
            session, "https://milpitas.watersmart.com", "a@b.c", "p"
        )
        client._request = AsyncMock(side_effect=[LOGIN, HOME])
        assert await client.login() == "0012345"
        args, kwargs = client._request.call_args
        assert args == ("POST", LOGIN_PATH)
        assert kwargs["data"] == {
            "token": "fresh-token",
            "email": "a@b.c",
            "password": "p",
        }
        assert kwargs["params"] == {"forceEmail": "1"}


async def test_configured_account_logs_in_before_fetching():
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(session, "https://milpitas.watersmart.com", "e", "p")
        client.account_number = "0012345"
        client._request = AsyncMock(side_effect=[LOGIN, HOME, HOME, json.dumps(CHART)])
        assert await client.fetch_hourly() == {3600: 2.5}
        assert client._request.call_args_list[0].args == ("GET", LOGIN_PATH)
        assert client._request.call_args_list[1].args == ("POST", LOGIN_PATH)
        assert client._authenticated


async def test_account_navigation_falls_back_to_usage_page():
    landing = "<main>Welcome to your water portal</main>"
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(session, "https://milpitas.watersmart.com", "e", "p")
        client.account_number = "0012345"
        client._request = AsyncMock(
            side_effect=[
                LOGIN,
                landing,
                landing,
                HOME,
                landing,
                HOME,
                json.dumps(CHART),
            ]
        )
        assert await client.fetch_hourly() == {3600: 2.5}
        usage_calls = [
            call
            for call in client._request.call_args_list
            if call.args == ("GET", USAGE_PATH)
        ]
        assert len(usage_calls) == 2


async def test_initial_login_rejects_different_configured_account():
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(session, "https://milpitas.watersmart.com", "e", "p")
        client.account_number = "9999999"
        client._request = AsyncMock(side_effect=[LOGIN, HOME])
        with pytest.raises(AccountMismatchError):
            await client.fetch_hourly()
        assert not client._authenticated


async def test_expired_session_relogs_once():
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(
            session, "https://milpitas.watersmart.com", "a@b.c", "p"
        )
        client.account_number = "0012345"
        client._authenticated = True
        client._request = AsyncMock(
            side_effect=[
                HOME,
                AuthenticationError(),
                LOGIN,
                HOME,
                HOME,
                json.dumps(CHART),
            ]
        )
        assert await client.fetch_hourly() == {3600: 2.5}
        assert client._request.call_count == 6


async def test_invalid_credentials_stop_retrying():
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(
            session, "https://milpitas.watersmart.com", "a@b.c", "p"
        )
        client._request = AsyncMock(side_effect=[LOGIN, LOGIN])
        with pytest.raises(AuthenticationError):
            await client.fetch_hourly()
        assert client._request.call_count == 2


async def test_changed_active_account_does_not_mix_history():
    async with aiohttp.ClientSession() as session:
        client = WaterSmartClient(
            session, "https://milpitas.watersmart.com", "a@b.c", "p"
        )
        client.account_number = "other-account"
        client._authenticated = True
        client._request = AsyncMock(return_value=HOME)
        with pytest.raises(AccountMismatchError):
            await client.fetch_hourly()
        assert client._request.call_count == 1


class Response:
    def __init__(self, status, path, body="", location=None):
        self.status = status
        self.url = URL("https://milpitas.watersmart.com" + path)
        self.headers = {"Location": location} if location else {}
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))
        return next(self.responses)


async def test_real_request_detects_redirect_to_login():
    session = Session(
        [
            Response(302, CHART_PATH, location=LOGIN_PATH),
            Response(200, LOGIN_PATH, LOGIN),
        ]
    )
    client = WaterSmartClient(session, "https://milpitas.watersmart.com", "e", "p")
    with pytest.raises(AuthenticationError):
        await client._request("GET", CHART_PATH)


async def test_real_request_blocks_cross_origin_redirect():
    session = Session([Response(302, HOME_PATH, location="https://attacker.org/")])
    client = WaterSmartClient(session, "https://milpitas.watersmart.com", "e", "p")
    with pytest.raises(WaterSmartError, match="outside"):
        await client._request("POST", LOGIN_PATH, data={"password": "secret"})
    assert len(session.calls) == 1
