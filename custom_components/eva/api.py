"""Asynchronous transport for the documented Eva App API."""

import json
import math
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import CLIENT_BRAND, CLIENT_ID, SCHEMA_VERSION, STREAM_IDLE_TIMEOUT


class EvaError(Exception):
    """An API request or event stream failed."""


class EvaAuthError(EvaError):
    """The server rejected authentication or home access."""


class EvaRateLimitError(EvaError):
    """The server requires a delay before retrying."""

    def __init__(self, retry_after: float) -> None:
        """Keep the server's retry delay without response bodies or credentials."""
        super().__init__("Eva request rate limited")
        self.retry_after = retry_after


def validate_base_url(value: str) -> str:
    """Require HTTPS and keep credentials out of URLs and logs."""
    url = URL(value)
    if (
        url.scheme != "https"
        or not url.host
        or url.user is not None
        or url.query_string
        or url.fragment
    ):
        raise ValueError(
            "Use an HTTPS API base URL without credentials, query or fragment"
        )
    return str(url).rstrip("/")


class EvaClient:
    """One client's HTTP and SSE transport using documented Basic authentication."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
    ) -> None:
        """Keep credentials local to requests, never on a shared session or URL."""
        self._session = session
        self._base_url = validate_base_url(base_url)
        if not username or not password:
            raise ValueError("Username and password are required")
        self._headers = {
            "Authorization": aiohttp.encode_basic_auth(username, password),
            "X-Client-ID": CLIENT_ID,
            "X-Client-Brand": CLIENT_BRAND,
            "X-Schema-Version": str(SCHEMA_VERSION),
            "X-Client-Language": "en",
        }
        self.retry_seconds = 5.0

    @staticmethod
    def _check_response(
        response: aiohttp.ClientResponse, statuses: tuple[int, ...] = (200,)
    ) -> None:
        if response.status in {401, 403}:
            raise EvaAuthError("Authentication or home access rejected")
        if response.status == 429:
            delay = response.headers.get("Retry-After", "60")
            raise EvaRateLimitError(float(delay) if delay.isdecimal() else 60)
        if response.status not in statuses:
            raise EvaError(f"Eva returned HTTP {response.status}")

    async def async_command(
        self,
        home_id: str,
        method: str,
        parts: tuple[str, ...],
        payload: dict | None = None,
    ) -> str | None:
        """Send a command; never retry a write or follow an authenticated redirect."""
        if not home_id or method not in {"PATCH", "POST"}:
            raise ValueError("Invalid command")
        path = "/".join(quote(part, safe="") for part in ("homes", home_id, *parts))
        try:
            async with self._session.request(
                method,
                f"{self._base_url}/{path}",
                headers={
                    **self._headers,
                    "X-Partition-Key": home_id[-1],
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                self._check_response(response, (200, 202, 204))
                if response.status == 204:
                    return None
                body = await response.read()
                if not body:
                    return None
                result = json.loads(body)
                if not isinstance(result, dict):
                    raise EvaError("Invalid command response")
                action_id = result.get("actionId")
                if action_id is not None and not isinstance(action_id, str):
                    raise EvaError("Invalid command response")
                return action_id
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise EvaError("Eva command request failed") from err

    async def async_get_homes(self) -> list[dict[str, str]]:
        """List only home IDs and names, for either documented response shape."""
        try:
            async with self._session.get(
                f"{self._base_url}/homes",
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                self._check_response(response)
                payload = await response.json()
            homes = payload.get("homes") if isinstance(payload, dict) else payload
            if not isinstance(homes, list) or any(
                not isinstance(home, dict)
                or not isinstance(home.get("id"), str)
                or not home["id"]
                or not isinstance(home.get("name"), str)
                for home in homes
            ):
                raise EvaError("Invalid home list")
            return [{"id": home["id"], "name": home["name"]} for home in homes]
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise EvaError("Unable to read the home list") from err

    async def async_get_charger_status(self, home_id: str, device_id: str) -> dict:
        """External chargers report separately from the home's SSE attributes."""
        path = "/".join(
            quote(part, safe="")
            for part in (
                "homes",
                home_id,
                "devices",
                device_id,
                "external",
                "evCharger",
                "status",
            )
        )
        try:
            async with self._session.get(
                f"{self._base_url}/{path}",
                headers={**self._headers, "X-Partition-Key": home_id[-1]},
                timeout=aiohttp.ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                self._check_response(response, (200, 202))
                payload = await response.json()
                if (
                    not isinstance(payload, dict)
                    or any(
                        type(payload.get(key)) is not bool
                        for key in ("carPluggedIn", "charging")
                    )
                    or type(payload.get("currentPower")) not in (int, float)
                    or not math.isfinite(payload["currentPower"])
                ):
                    raise EvaError("Invalid external charger status")
                return {
                    key: payload[key]
                    for key in ("carPluggedIn", "charging", "currentPower")
                }
        except (aiohttp.ClientError, TimeoutError, ValueError, OverflowError) as err:
            raise EvaError("Unable to read external charger status") from err

    async def async_events(
        self,
        home_id: str,
        client_id: str,
        last_seen_event_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Read one SSE connection; the coordinator owns reconnection and shutdown."""
        if not home_id or not client_id:
            raise ValueError("Home and client IDs are required")
        headers = {
            **self._headers,
            "Accept": "text/event-stream",
            "X-Partition-Key": home_id[-1],
        }
        params = {"lastSeenEventId": last_seen_event_id} if last_seen_event_id else {}
        path = f"/homes/{quote(home_id, safe='')}/clients/{quote(client_id, safe='')}"
        try:
            async with self._session.get(
                f"{self._base_url}{path}",
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(
                    total=None, sock_connect=30, sock_read=STREAM_IDLE_TIMEOUT
                ),
                allow_redirects=False,
                read_bufsize=4 * 1024 * 1024,
            ) as response:
                self._check_response(response)
                if response.content_type != "text/event-stream":
                    raise EvaError("Expected an SSE response")
                data: list[str] = []
                size = 0
                async for raw in response.content:
                    line = raw.decode("utf-8-sig").rstrip("\r\n")
                    if not line:
                        if data:
                            event = json.loads("\n".join(data))
                            if not isinstance(event, dict) or not isinstance(
                                event.get("eventType"), str
                            ):
                                raise EvaError("Invalid SSE event")
                            yield event
                        data = []
                        size = 0
                    elif not line.startswith(":"):
                        field, _, value = line.partition(":")
                        value = value.removeprefix(" ")
                        if field == "retry" and value.isascii() and value.isdecimal():
                            self.retry_seconds = max(1.0, int(value) / 1000)
                        elif field == "data":
                            size += len(raw)
                            if size > 8 * 1024 * 1024:
                                raise EvaError("SSE event exceeds size limit")
                            data.append(value)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise EvaError("Event stream interrupted or invalid") from err
