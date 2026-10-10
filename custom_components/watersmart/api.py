"""Cookie-based WaterSmart client derived from the supplied HAR.

No credentials, cookies, or personal information from the capture are embedded.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

import aiohttp
from yarl import URL

LOGIN_PATH = "/index.php/welcome/login"
HOME_PATH = "/index.php/home/index"
USAGE_PATH = "/index.php/trackUsage"
CHART_PATH = "/index.php/rest/v1/Chart/RealTimeChart"


class WaterSmartError(Exception):
    """An unexpected response or service failure."""


class AuthenticationError(WaterSmartError):
    """The portal rejected credentials or expired its session."""


class AccountMismatchError(WaterSmartError):
    """The selected portal account changed."""


class AccountNotFoundError(WaterSmartError):
    """The page has no labeled active account number."""


def normalize_url(value: str) -> str:
    """Only accept HTTPS utility portals; never send credentials to arbitrary hosts."""
    parsed = urlsplit(value.strip())
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or not host.endswith(".watersmart.com")
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter an HTTPS WaterSmart utility portal URL")
    return f"https://{host}"


class LoginParser(HTMLParser):
    """Read a hidden login token without depending on attribute order."""

    def __init__(self) -> None:
        super().__init__()
        self.token = ""
        self.is_login = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "input":
            if attributes.get("name") == "token":
                self.token = attributes.get("value") or ""
            if (
                attributes.get("name") == "password"
                or attributes.get("type") == "password"
            ):
                self.is_login = True


class AccountParser(HTMLParser):
    """Collect rendered text without depending on the portal's tag layout."""

    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, bool]] = []
        self.parts: list[str] = []
        self.navigation: list[str] = []
        self.has_navigation = False

    def handle_starttag(self, tag, attrs) -> None:
        navigation = dict(attrs).get("id") == "account-navigation"
        self.has_navigation |= navigation
        if tag not in self._VOID_TAGS:
            self.stack.append((tag, navigation))

    def handle_endtag(self, tag) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data) -> None:
        if any(tag in {"script", "style"} for tag, _ in self.stack):
            return
        self.parts.append(data)
        if any(navigation for _, navigation in self.stack):
            self.navigation.append(data)


def account_from_html(html: str) -> str:
    """Read a labeled account number, rejecting missing or ambiguous identity."""
    parser = AccountParser()
    parser.feed(html)
    parts = parser.navigation if parser.has_navigation else parser.parts
    text = " ".join(" ".join(parts).split())
    candidates = re.findall(
        r"\bAccount\s+(?:Number|No\.?|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9._-]*)",
        text,
        re.IGNORECASE,
    )
    accounts = {value for value in candidates if any(c.isdigit() for c in value)}
    if not accounts:
        raise AccountNotFoundError("The portal did not identify its active account")
    if len(accounts) != 1:
        raise WaterSmartError("The portal identified multiple active accounts")
    return accounts.pop()


def parse_chart(payload: object) -> dict[int, float]:
    """Validate epoch-encoded local wall hours; coordinator applies the timezone."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise WaterSmartError("Unexpected RealTimeChart response")
    data = payload["data"]
    if data.get("hideHourly"):
        raise WaterSmartError("Hourly readings are disabled for this account")
    series = data.get("series")
    if not isinstance(series, list):
        raise WaterSmartError("RealTimeChart did not return hourly readings")
    result: dict[int, float] = {}
    for row in series:
        if not isinstance(row, dict):
            raise WaterSmartError("Invalid hourly reading")
        # Missing readings are unknown, not zero usage.
        if row.get("gallons") is None:
            continue
        try:
            raw_timestamp = row["read_datetime"]
            if isinstance(raw_timestamp, bool) or isinstance(row["gallons"], bool):
                raise ValueError
            timestamp = int(raw_timestamp)
            gallons = float(row["gallons"])
            if (
                float(raw_timestamp) != timestamp
                or timestamp < 0
                or timestamp % 3600
                or not math.isfinite(gallons)
                or gallons < 0
            ):
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError) as err:
            raise WaterSmartError("Invalid hourly timestamp or volume") from err
        # The captured API has one duplicate timestamp; last returned value wins.
        result[timestamp] = gallons
    return dict(sorted(result.items()))


class WaterSmartClient:
    """Own an isolated cookie jar for each configured account."""

    def __init__(
        self, session: aiohttp.ClientSession, url: str, email: str, password: str
    ) -> None:
        self.session = session
        self.url = normalize_url(url)
        self.email = email
        self.password = password
        self.account_number: str | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()

    async def _active_account(self, html: str) -> str:
        """Use the usage page when the landing page omits account navigation."""
        try:
            return account_from_html(html)
        except AccountNotFoundError:
            return account_from_html(await self._request("GET", USAGE_PATH))

    async def _request(self, method: str, path: str, **kwargs) -> str:
        """Follow only same-origin redirects and keep errors free of secrets."""
        url = self.url + path
        for _ in range(6):
            async with self.session.request(
                method, url, allow_redirects=False, **kwargs
            ) as response:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        raise WaterSmartError("Portal redirect has no destination")
                    target = response.url.join(URL(location))
                    if str(target.origin()) != self.url:
                        raise WaterSmartError("Portal redirected outside its origin")
                    url = str(target)
                    if response.status in (301, 302, 303):
                        method = "GET"
                        kwargs.pop("data", None)
                    kwargs.pop("params", None)
                    continue
                if response.status in (401, 403):
                    raise AuthenticationError("WaterSmart authentication required")
                if response.status != 200:
                    raise WaterSmartError(f"WaterSmart returned HTTP {response.status}")
                text = await response.text()
                parser = LoginParser()
                parser.feed(text)
                if path != LOGIN_PATH and (
                    parser.is_login or LOGIN_PATH in str(response.url)
                ):
                    raise AuthenticationError("WaterSmart session expired")
                return text
        raise WaterSmartError("Too many portal redirects")

    async def _login(self) -> str:
        self._authenticated = False
        self.session.cookie_jar.clear()
        login_page = await self._request("GET", LOGIN_PATH)
        parser = LoginParser()
        parser.feed(login_page)
        html = await self._request(
            "POST",
            LOGIN_PATH,
            params={"forceEmail": "1"},
            data={
                "token": parser.token,
                "email": self.email,
                "password": self.password,
            },
            headers={"Origin": self.url, "Referer": self.url + LOGIN_PATH},
        )
        parser = LoginParser()
        parser.feed(html)
        if parser.is_login:
            raise AuthenticationError("WaterSmart rejected the email or password")
        # Some portals redirect to a landing page without navigation.
        try:
            account = account_from_html(html)
        except AccountNotFoundError:
            account = await self._active_account(await self._request("GET", HOME_PATH))
        if self.account_number is not None and account != self.account_number:
            raise AccountMismatchError("The active WaterSmart account changed")
        self.account_number = account
        self._authenticated = True
        return account

    async def login(self) -> str:
        async with self._lock:
            return await self._login()

    async def fetch_hourly(self) -> dict[int, float]:
        """Retry an expired session once, using stored credentials."""
        async with self._lock:
            # A stored account number identifies the entry, not a logged-in session.
            if not self._authenticated:
                await self._login()
            for attempt in range(2):
                try:
                    html = await self._request("GET", HOME_PATH)
                    if await self._active_account(html) != self.account_number:
                        raise AccountMismatchError(
                            "The active WaterSmart account changed"
                        )
                    text = await self._request(
                        "GET",
                        CHART_PATH,
                        headers={"X-Requested-With": "XMLHttpRequest"},
                    )
                    try:
                        payload = json.loads(text)
                    except ValueError as err:
                        raise WaterSmartError(
                            "RealTimeChart returned invalid JSON"
                        ) from err
                    return parse_chart(payload)
                except AuthenticationError:
                    self._authenticated = False
                    if attempt:
                        raise
                    await self._login()
        raise AuthenticationError("WaterSmart authentication required")
