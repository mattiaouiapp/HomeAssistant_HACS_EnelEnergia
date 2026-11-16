"""Client for the Enel customer area (SAML login + consumption API)."""

from __future__ import annotations

from datetime import date, datetime
from html.parser import HTMLParser
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

LOGIN_PAGE_URL = "https://www.enel.it/it/login"
LOGIN_URL = "https://accounts.enel.com/samlsso"
SAMLAUTH_URL = "https://www.enel.it/bin/samlauth"
AGGREGATE_CONSUMPTION_URL = "https://www.enel.it/bin/areaclienti/auth/aggregateConsumption"

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)


class EnelGridError(Exception):
    """Generic error talking to Enel."""


class EnelGridAuthError(EnelGridError):
    """Invalid credentials or login flow changed."""


class _InputCollector(HTMLParser):
    """Collect name -> value of every <input> in a page."""

    def __init__(self) -> None:
        super().__init__()
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "input":
            return
        attr = dict(attrs)
        if name := attr.get("name"):
            self.inputs[name] = attr.get("value") or ""


def _find_input(html: str, name: str) -> str | None:
    parser = _InputCollector()
    parser.feed(html)
    return parser.inputs.get(name)


def format_enel_date(day: date) -> str:
    """Format a date as expected by the Enel API (DDMMYYYY)."""
    return day.strftime("%d%m%Y")


class EnelGridClient:
    """Authenticated Enel session.

    Use as an async context manager: login happens on enter, the HTTP session
    is always closed on exit (also on errors). Multiple fetches can be done
    with a single login.
    """

    def __init__(self, username: str, password: str, pod: str, user_number: int | str) -> None:
        self._username = username
        self._password = password
        self._pod = pod
        self._user_number = user_number
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> EnelGridClient:
        self._session = aiohttp.ClientSession(timeout=REQUEST_TIMEOUT)
        try:
            await self.login()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("EnelGridClient used outside of 'async with'")
        return self._session

    async def login(self) -> None:
        """Run the full SAML login flow."""
        try:
            async with self.session.get(LOGIN_PAGE_URL) as response:
                response.raise_for_status()
                session_data_key = _find_input(await response.text(), "sessionDataKey")
            if not session_data_key:
                raise EnelGridAuthError("sessionDataKey not found on login page (Enel login page changed?)")

            async with self.session.post(
                LOGIN_URL,
                data={
                    "username": self._username,
                    "password": self._password,
                    "sessionDataKey": session_data_key,
                    "tocommonauth": "true",
                },
            ) as response:
                response.raise_for_status()
                saml_response = _find_input(await response.text(), "SAMLResponse")
            if not saml_response:
                raise EnelGridAuthError("SAMLResponse not found after login: invalid credentials?")

            async with self.session.post(SAMLAUTH_URL, data={"SAMLResponse": saml_response}) as response:
                response.raise_for_status()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EnelGridError(f"Error during Enel login: {err}") from err

        _LOGGER.debug("Enel login completed")

    async def fetch_consumption(self, start: date, end: date) -> dict[str, Any]:
        """Return the raw aggregateConsumption JSON for [start, end]."""
        params = {
            "pod": self._pod,
            "userNumber": str(self._user_number),
            "validityFrom": format_enel_date(start),
            "validityTo": format_enel_date(end),
            "_": str(int(datetime.now().timestamp() * 1000)),
        }
        _LOGGER.debug("Fetching Enel consumption %s -> %s", start, end)
        try:
            async with self.session.get(AGGREGATE_CONSUMPTION_URL, params=params) as response:
                if response.status in (401, 403):
                    raise EnelGridAuthError(f"Enel API returned HTTP {response.status}")
                response.raise_for_status()
                # When the session is not valid Enel answers with an HTML page.
                if "json" not in response.headers.get("Content-Type", ""):
                    raise EnelGridAuthError("Enel API did not return JSON (session not authenticated?)")
                return await response.json()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise EnelGridError(f"Error fetching Enel consumption: {err}") from err
