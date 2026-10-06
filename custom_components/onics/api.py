"""Asynchronous, read-only transport for the documented Onics App API."""

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import aiohttp
from yarl import URL

from .const import CLIENT_ID, STREAM_IDLE_TIMEOUT


class OnicsError(Exception):
    """An API request or event stream failed."""


class OnicsAuthError(OnicsError):
    """The server rejected authentication or home access."""


class OnicsRateLimitError(OnicsError):
    """The server requires a delay before retrying."""

    def __init__(self, retry_after: float) -> None:
        """Keep the server's retry delay without response bodies or credentials."""
        super().__init__("Onics request rate limited")
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


class OnicsClient:
    """One client's HTTP and SSE transport; authentication is supplied by its session."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        client_brand: str,
        schema_version: int,
    ) -> None:
        """Use explicitly supplied deployment settings, without schema defaults."""
        self._session = session
        self._base_url = validate_base_url(base_url)
        if (
            not client_brand.strip()
            or type(schema_version) is not int
            or schema_version < 1
        ):
            raise ValueError("Client brand and a confirmed schema version are required")
        self._headers = {
            "X-Client-ID": CLIENT_ID,
            "X-Client-Brand": client_brand,
            "X-Schema-Version": str(schema_version),
            "X-Client-Language": "en",
        }
        self.retry_seconds = 5.0

    @staticmethod
    def _check_response(response: aiohttp.ClientResponse) -> None:
        if response.status in {401, 403}:
            raise OnicsAuthError("Authentication or home access rejected")
        if response.status == 429:
            delay = response.headers.get("Retry-After", "60")
            raise OnicsRateLimitError(float(delay) if delay.isdecimal() else 60)
        if response.status != 200:
            raise OnicsError(f"Onics returned HTTP {response.status}")

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
                raise OnicsError("Invalid home list")
            return [{"id": home["id"], "name": home["name"]} for home in homes]
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise OnicsError("Unable to read the home list") from err

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
                    raise OnicsError("Expected an SSE response")
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
                                raise OnicsError("Invalid SSE event")
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
                                raise OnicsError("SSE event exceeds size limit")
                            data.append(value)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise OnicsError("Event stream interrupted or invalid") from err
