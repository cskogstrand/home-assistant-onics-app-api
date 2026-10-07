"""Run the actual SSE parser against an in-memory aiohttp byte stream."""

from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.eva.api import (
    EvaAuthError,
    EvaClient,
    EvaError,
    EvaRateLimitError,
    validate_base_url,
)


def make_client(status=200, wire=b"", payload=None):
    response = MagicMock(status=status, content_type="text/event-stream", headers={})
    response.json = AsyncMock(return_value=payload)
    response.content = aiohttp.StreamReader(
        MagicMock(_reading_paused=False), limit=2**23
    )
    # Chunk boundaries deliberately split JSON and SSE field names.
    for offset in range(0, len(wire), 7):
        response.content.feed_data(wire[offset : offset + 7])
    response.content.feed_eof()
    session = MagicMock()
    session.get.return_value.__aenter__ = AsyncMock(return_value=response)
    session.get.return_value.__aexit__ = AsyncMock(return_value=False)
    return (
        EvaClient(
            session,
            "https://api.example.invalid/prefix",
            "test@example.invalid",
            "test-password",
        ),
        session,
        response,
    )


async def test_sse_framing_headers_retry_and_replay():
    client, session, _ = make_client(
        wire=(
            b"\xef\xbb\xbf: comment\r\nretry: 7200\r\n\r\nevent: test-home\r\n"
            b'data: {"eventType": "keepAlive",\r\ndata: "id": "test-event"}\r\n\r\n'
            b'data: {"eventType": "keepAlive"}'  # Incomplete frame is not dispatched.
        )
    )
    events = [
        event
        async for event in client.async_events("test-home", "test-client", "previous")
    ]
    assert events == [{"eventType": "keepAlive", "id": "test-event"}]
    assert client.retry_seconds == 7.2
    args, kwargs = session.get.call_args
    assert (
        args[0]
        == "https://api.example.invalid/prefix/homes/test-home/clients/test-client"
    )
    assert kwargs["headers"]["X-Partition-Key"] == "e"
    assert kwargs["headers"]["X-Client-Brand"] == "eva"
    assert kwargs["headers"]["X-Schema-Version"] == "7"
    assert kwargs["params"] == {"lastSeenEventId": "previous"}
    assert kwargs["timeout"].sock_read == 15
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["Authorization"] == aiohttp.encode_basic_auth(
        "test@example.invalid", "test-password"
    )
    session.get.return_value.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "status,error,message",
    [
        (401, EvaAuthError, "HTTP 401: credentials are missing or invalid"),
        (403, EvaAuthError, "HTTP 403: account lacks access or permission"),
        (429, EvaRateLimitError, "Eva request rate limited"),
        (503, EvaError, "Eva returned HTTP 503"),
    ],
)
async def test_http_failures_release_response(status, error, message):
    client, session, response = make_client(status=status)
    response.headers = {"Retry-After": "42"}
    with pytest.raises(error, match=message) as exc:
        await anext(client.async_events("test-home", "test-client"))
    if status == 429:
        assert exc.value.retry_after == 42
    session.get.return_value.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "wire,message",
    [
        (b"data: []\n\n", "must be a JSON object with a string eventType"),
        (b"data: private-invalid-json\n\n", "contains invalid JSON"),
        (
            b'data: {"eventType": []}\n\n',
            "must be a JSON object with a string eventType",
        ),
        (b"data: \xffprivate-invalid-utf8\n\n", "contains invalid UTF-8"),
        (b"retry: " + b"9" * 5000 + b"\n\n", "contains an invalid field"),
    ],
)
async def test_bad_sse_reports_format_failure_without_payload(wire, message):
    client, session, _ = make_client(wire=wire)
    with pytest.raises(EvaError, match=message) as exc:
        await anext(client.async_events("test-home", "test-client"))
    assert "private" not in str(exc.value)
    session.get.return_value.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "error,message",
    [
        (
            aiohttp.ClientConnectionError,
            "Eva SSE transport failed (ClientConnectionError)",
        ),
        (aiohttp.ClientError, "Eva SSE transport failed (ClientError)"),
        (aiohttp.ClientPayloadError, "Eva SSE response body is incomplete or corrupt"),
    ],
)
async def test_sse_transport_failure_reports_cause_without_private_details(
    error, message
):
    client, session, response = make_client()
    response.content.set_exception(error("private request URL or response data"))
    with pytest.raises(EvaError) as exc:
        await anext(client.async_events("test-home", "test-client"))
    assert str(exc.value) == message
    session.get.return_value.__aexit__.assert_awaited_once()


async def test_sse_socket_timeout_reaches_coordinator_and_releases_response():
    client, session, response = make_client()
    response.content.set_exception(aiohttp.SocketTimeoutError("Read timed out"))
    with pytest.raises(TimeoutError):
        await anext(client.async_events("test-home", "test-client"))
    session.get.return_value.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "payload",
    [
        [{"id": "test-home", "name": "Test home", "rooms": []}],
        {"homes": [{"id": "test-home", "name": "Test home"}]},
    ],
)
async def test_home_list_retains_only_identity_and_name(payload):
    client, session, _ = make_client(payload=payload)
    assert await client.async_get_homes() == [{"id": "test-home", "name": "Test home"}]
    kwargs = session.get.call_args.kwargs
    assert kwargs["headers"]["X-Client-Brand"] == "eva"
    assert kwargs["headers"]["X-Schema-Version"] == "7"
    assert kwargs["headers"]["Authorization"] == aiohttp.encode_basic_auth(
        "test@example.invalid", "test-password"
    )
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid",
        "https://u:p@example.invalid",
        "https://example.invalid/?token=test",
        "https://example.invalid/#token",
        "not-a-url",
    ],
)
def test_base_url_rejects_unsafe_or_ambiguous_settings(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


@pytest.mark.parametrize("status", [200, 202, 204])
async def test_command_method_escaping_headers_and_success(status):
    client, session, response = make_client(status=status)
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    session.request.return_value.__aexit__ = AsyncMock(return_value=False)
    response.read = AsyncMock(return_value=b'{"actionId":"test-action"}')
    assert await client.async_command(
        "home/id",
        "PATCH",
        ("devices", "device/id", "attributes", "displayText", "a/b ?#"),
    ) == (None if status == 204 else "test-action")
    args, kwargs = session.request.call_args
    assert args == (
        "PATCH",
        "https://api.example.invalid/prefix/homes/home%2Fid/devices/device%2Fid/attributes/displayText/a%2Fb%20%3F%23",
    )
    assert kwargs["headers"]["X-Partition-Key"] == "d"
    assert kwargs["headers"]["X-Schema-Version"] == "7"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Authorization"] == aiohttp.encode_basic_auth(
        "test@example.invalid", "test-password"
    )
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"].total == 30
    session.request.return_value.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "status,error",
    [(401, EvaAuthError), (429, EvaRateLimitError), (302, EvaError), (500, EvaError)],
)
async def test_command_errors_are_not_retried(status, error):
    client, session, response = make_client(status=status)
    session.request.return_value.__aenter__ = AsyncMock(return_value=response)
    session.request.return_value.__aexit__ = AsyncMock(return_value=False)
    with pytest.raises(error):
        await client.async_command(
            "test-home", "POST", ("devices", "test-device", "identify")
        )
    assert session.request.call_count == 1
    session.request.return_value.__aexit__.assert_awaited_once()


async def test_external_charger_status_validation():
    client, session, response = make_client(
        status=202,
        payload={
            "carPluggedIn": True,
            "charging": False,
            "currentPower": 0,
            "ignored": "private",
        },
    )
    assert await client.async_get_charger_status("test-home", "test-device") == {
        "carPluggedIn": True,
        "charging": False,
        "currentPower": 0,
    }
    assert session.get.call_args.args[0].endswith("/external/evCharger/status")
    assert session.get.call_args.kwargs["headers"][
        "Authorization"
    ] == aiohttp.encode_basic_auth("test@example.invalid", "test-password")
    response.json.return_value = {
        "carPluggedIn": "true",
        "charging": False,
        "currentPower": 0,
    }
    with pytest.raises(EvaError):
        await client.async_get_charger_status("test-home", "test-device")
