"""Exercise reconnects, failure states and cancellation without network access."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    HomeAssistantError,
)
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eva.api import EvaAuthError, EvaClient, EvaError
from custom_components.eva.coordinator import EvaCoordinator
from custom_components.eva.sensor import DESCRIPTIONS, EvaSensor


def make_coordinator(hass, events):
    entry = MockConfigEntry(
        domain="eva",
        unique_id="test:test-home",
        data={"home_id": "test-home", "sse_client_id": "test-client"},
    )
    entry.add_to_hass(hass)
    client = MagicMock(spec=EvaClient)
    client.retry_seconds = 0
    client.async_events = MagicMock(side_effect=events)
    coordinator = EvaCoordinator(hass, entry, client)
    entry.runtime_data = coordinator
    return coordinator


@pytest.mark.parametrize("failure", [EvaError("Eva returned HTTP 415"), None])
async def test_command_distinguishes_request_failure_from_missing_confirmation(
    hass, snapshot, failure
):
    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.last_update_success = True
    coordinator.client.async_command = AsyncMock(
        side_effect=failure, return_value="test-action"
    )
    expected = (
        "Eva returned HTTP 415"
        if failure
        else "Eva accepted the command but did not confirm it within 30 seconds"
    )
    timeout = asyncio.timeout
    with (
        patch(
            "custom_components.eva.coordinator.asyncio.timeout",
            side_effect=lambda _: timeout(0),
        ),
        pytest.raises(HomeAssistantError, match=expected),
    ):
        await coordinator.async_command(
            "PATCH", ("devices", "test-device", "attributes", "on", "true")
        )
    coordinator.client.async_command.assert_awaited_once()
    assert not coordinator._command_listeners


@pytest.mark.parametrize("resource", ["devices", "groups"])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_new_commands_replace_old_waits_without_blocking(
    hass, snapshot, resource, outcome
):
    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.last_update_success = True
    sent = asyncio.Queue()

    async def command(home_id, method, parts, payload):
        action_id = f"{parts[1]}-{parts[-1]}"
        sent.put_nowait(action_id)
        return action_id

    coordinator.client.async_command = AsyncMock(side_effect=command)

    def start(target, value):
        return hass.async_create_background_task(
            coordinator.async_command(
                "PATCH" if resource == "devices" else "POST",
                (resource, target, "attributes", "dimLevel", value),
            ),
            "test command",
        )

    def receive(event_type, action_id=None):
        for listener in tuple(coordinator._command_listeners):
            listener({"eventType": event_type, "actionId": action_id})

    first = start("lamp", "40")
    assert await sent.get() == "lamp-40"
    second = start("lamp", "60")
    other = start("other-lamp", "50")
    try:
        assert await sent.get() == "lamp-60"
        assert await sent.get() == "other-lamp-50"
        assert await first is False
        assert (resource, "lamp") in coordinator._pending_commands
        receive("deviceAttributeChanged", "lamp-40")
        receive("actionTimeout", "lamp-40")
        receive("deviceAttributeSent", "lamp-60")
        receive("deviceAttributeChanged")
        receive("deviceAttributeChanged", "unrelated-action")
        receive("deviceAttributeChanged", "other-lamp-50")
        assert await other is True
        assert sent.empty()
        assert not second.done()

        if outcome == "cancel":
            second.cancel()
            with pytest.raises(asyncio.CancelledError):
                await second
        elif outcome == "failure":
            receive("actionTimeout", "lamp-60")
            with pytest.raises(HomeAssistantError, match="could not complete"):
                await second
        else:
            receive("deviceAttributeChanged", "lamp-60")
            assert await second is True

        assert not coordinator._command_listeners
        assert not coordinator._pending_commands
    finally:
        for task in (first, second, other):
            task.cancel()
        await asyncio.gather(first, second, other, return_exceptions=True)


async def test_superseded_http_response_cannot_replace_latest_confirmation(
    hass, snapshot
):
    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.last_update_success = True
    first_sent = asyncio.Event()
    first_response = asyncio.Event()

    async def command(home_id, method, parts, payload):
        if parts[-1] == "40":
            first_sent.set()
            await first_response.wait()
            return "old-action"
        # The latest success can arrive before either HTTP response.
        for listener in tuple(coordinator._command_listeners):
            listener({"eventType": "deviceAttributeChanged", "actionId": "new-action"})
        return "new-action"

    coordinator.client.async_command = AsyncMock(side_effect=command)
    first = hass.async_create_background_task(
        coordinator.async_command(
            "PATCH", ("devices", "lamp", "attributes", "dimLevel", "40")
        ),
        "test delayed HTTP response",
    )
    try:
        await first_sent.wait()
        assert (
            await coordinator.async_command(
                "PATCH", ("devices", "lamp", "attributes", "dimLevel", "60")
            )
            is True
        )
        first_response.set()
        assert await first is False
        assert not coordinator._pending_commands
        assert not coordinator._command_listeners
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)


async def test_snapshot_partial_update_disconnect_reconnect_and_shutdown(
    hass, snapshot
):
    queue = asyncio.Queue()
    closed = asyncio.Event()
    connections = asyncio.Queue()

    async def stream(home_id, client_id, last_seen_event_id):
        connections.put_nowait((home_id, client_id, last_seen_event_id))
        try:
            while True:
                event = await queue.get()
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            closed.set()

    coordinator = make_coordinator(hass, stream)
    changed = asyncio.Event()
    unsub = coordinator.async_add_listener(changed.set)
    await coordinator._async_setup()
    sensor = EvaSensor(coordinator, "test-device", DESCRIPTIONS[0])
    assert not sensor.available
    assert await connections.get() == ("test-home", "test-client", None)
    queue.put_nowait(snapshot)
    await coordinator._async_update_data()
    assert sensor.available
    assert sensor.native_value == 21.5
    assert sensor.unique_id == "test:test-home:test-device:temperature"
    changed.clear()
    queue.put_nowait(
        {
            "eventType": "deviceAttributeChanged",
            "id": "test-event-2",
            "deviceId": "test-device",
            "name": "temperature",
            "value": 0,
        }
    )
    await asyncio.wait_for(changed.wait(), 2)
    assert sensor.native_value == 0
    changed.clear()
    queue.put_nowait(EvaError("test disconnect"))
    await asyncio.wait_for(changed.wait(), 2)
    assert not sensor.available
    assert (
        str(coordinator.last_exception) == "test disconnect; reconnecting automatically"
    )
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert await asyncio.wait_for(connections.get(), 3) == (
        "test-home",
        "test-client",
        "test-event-2",
    )
    queue.put_nowait(snapshot)
    changed.clear()
    await asyncio.wait_for(changed.wait(), 2)
    assert sensor.available
    closed.clear()
    unsub()
    await coordinator.async_shutdown()
    assert closed.is_set()
    assert coordinator._task is None


async def test_server_closure_reconnects_with_cursor_retry_and_availability(
    hass, snapshot, caplog
):
    caplog.set_level("DEBUG", logger="custom_components.eva.coordinator")
    connections = asyncio.Queue()
    close_stream = asyncio.Queue()
    closed = []

    async def stream(home_id, client_id, last_seen_event_id):
        connection = coordinator.client.async_events.call_count
        connections.put_nowait((home_id, client_id, last_seen_event_id))
        try:
            yield snapshot
            yield {"eventType": "keepAlive", "id": f"test-event-{connection}"}
            await close_stream.get()
        finally:
            closed.append(connection)

    coordinator = make_coordinator(hass, stream)
    coordinator.client.retry_seconds = 1.1
    sensor = EvaSensor(coordinator, "test-device", DESCRIPTIONS[0])
    with patch.object(
        coordinator,
        "async_set_update_error",
        wraps=coordinator.async_set_update_error,
    ) as update_error:
        await coordinator._async_setup()
        try:
            await coordinator._async_update_data()
            closed_at = hass.loop.time()
            for connection in range(1, 4):
                assert await asyncio.wait_for(connections.get(), 3) == (
                    "test-home",
                    "test-client",
                    None if connection == 1 else f"test-event-{connection - 1}",
                )
                assert closed == list(range(1, connection))
                assert sensor.available
                assert sensor.native_value == 21.5
                if connection > 1:
                    assert (
                        hass.loop.time() - closed_at >= coordinator.client.retry_seconds
                    )
                if connection < 3:
                    closed_at = hass.loop.time()
                    close_stream.put_nowait(None)
            update_error.assert_not_called()
            assert "Error requesting eva data" not in caplog.text
            assert "Eva SSE stream closed; reconnecting automatically" in caplog.text
            assert "API streams normally close after 10 minutes" in caplog.text
            assert "Reconnecting Eva SSE stream in 1.1 seconds" in caplog.text
            assert "Eva SSE home snapshot received; stream active" in caplog.text
        finally:
            await coordinator.async_shutdown()
    assert closed == [1, 2, 3]
    assert coordinator._task is None


async def test_stream_closed_without_snapshot_is_an_error(hass):
    closed = asyncio.Event()

    async def stream(*args):
        closed.set()
        return
        yield  # Make this an async generator, like the real transport.

    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    try:
        await asyncio.wait_for(closed.wait(), 1)
        assert not coordinator.last_update_success
        assert isinstance(coordinator.last_exception, UpdateFailed)
        assert (
            str(coordinator.last_exception)
            == "Eva SSE stream closed before a home snapshot; reconnecting automatically"
        )
    finally:
        await coordinator.async_shutdown()


async def test_initial_auth_failure_stops_stream(hass):
    async def stream(*args):
        raise EvaAuthError("rejected")
        yield  # Make this an async generator, like the real transport.

    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    with pytest.raises(ConfigEntryAuthFailed, match="rejected"):
        await coordinator._async_update_data()
    assert not coordinator.last_update_success
    assert str(coordinator.last_exception) == (
        "rejected; automatic reconnect stopped; reauthentication required"
    )
    assert coordinator._task.done()
    await coordinator.async_shutdown()


async def test_live_auth_failure_starts_reauth_once(hass, snapshot):
    queue = asyncio.Queue()

    async def stream(*args):
        yield snapshot
        await queue.get()
        raise EvaAuthError("rejected")

    coordinator = make_coordinator(hass, stream)
    with patch.object(MockConfigEntry, "async_start_reauth") as reauth:
        await coordinator._async_setup()
        await coordinator._async_update_data()
        queue.put_nowait(True)
        await coordinator._task
        reauth.assert_called_once_with(hass)
    assert not coordinator.last_update_success
    await coordinator.async_shutdown()


@pytest.mark.parametrize("socket_timeout", [False, True])
@pytest.mark.parametrize("offline", [None, "gateway", "device"])
async def test_silent_connection_reconnects_without_changing_availability(
    hass, snapshot, caplog, socket_timeout, offline
):
    caplog.set_level("DEBUG", logger="custom_components.eva.coordinator")
    if offline == "gateway":
        snapshot["home"]["gateway"]["online"] = False
    elif offline == "device":
        snapshot["home"]["rooms"][0]["devices"][0]["online"] = False
    closed = asyncio.Event()
    connections = asyncio.Queue()

    async def stream(home_id, client_id, last_seen_event_id):
        connections.put_nowait((home_id, client_id, last_seen_event_id))
        try:
            yield snapshot
            if socket_timeout:
                raise aiohttp.SocketTimeoutError("Read timed out")
            await asyncio.Event().wait()
        finally:
            closed.set()

    coordinator = make_coordinator(hass, stream)
    sensor = EvaSensor(coordinator, "test-device", DESCRIPTIONS[0])
    with (
        patch("custom_components.eva.coordinator.STREAM_IDLE_TIMEOUT", 0.01),
        patch.object(
            coordinator,
            "async_set_update_error",
            wraps=coordinator.async_set_update_error,
        ) as update_error,
    ):
        await coordinator._async_setup()
        try:
            await coordinator._async_update_data()
            assert await connections.get() == ("test-home", "test-client", None)
            await asyncio.wait_for(closed.wait(), 1)
            assert coordinator.last_update_success
            assert sensor.available is (offline is None)
            assert sensor.native_value == 21.5
            assert await coordinator._async_update_data() is coordinator.data
            assert await asyncio.wait_for(connections.get(), 3) == (
                "test-home",
                "test-client",
                "test-event-1",
            )
            assert sensor.available is (offline is None)
            update_error.assert_not_called()
            assert "Error requesting eva data" not in caplog.text
            assert "Eva SSE received no events for 0.01 seconds" in caplog.text
            assert "keepAlive is normally sent every 5 seconds" in caplog.text
        finally:
            await coordinator.async_shutdown()
    assert coordinator._task is None


async def test_timeout_before_home_snapshot_stays_unavailable(hass):
    closed = asyncio.Event()

    async def stream(*args):
        try:
            await asyncio.Event().wait()
            yield  # Make this an async generator, like the real transport.
        finally:
            closed.set()

    coordinator = make_coordinator(hass, stream)
    with patch("custom_components.eva.coordinator.STREAM_IDLE_TIMEOUT", 0.01):
        await coordinator._async_setup()
        await asyncio.wait_for(closed.wait(), 1)
    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, UpdateFailed)
    assert str(coordinator.last_exception) == (
        "Eva SSE timed out before receiving a home snapshot; reconnecting automatically"
    )
    await coordinator.async_shutdown()


async def test_kill_client_stops_without_retrying_setup(hass):
    async def stream(*args):
        yield {"eventType": "killClient"}

    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    with pytest.raises(
        ConfigEntryError, match=r"killClient.*Automatic reconnect stopped"
    ):
        await coordinator._async_update_data()
    assert coordinator._task.done()
    coordinator.client.async_events.assert_called_once()
    await coordinator.async_shutdown()


async def test_reset_client_discards_replay_cursor(hass, snapshot):
    connections = asyncio.Queue()
    reset = asyncio.Event()

    async def stream(home_id, client_id, last_seen_event_id):
        connections.put_nowait(last_seen_event_id)
        yield snapshot
        await reset.wait()
        if coordinator.client.async_events.call_count == 1:
            yield {"eventType": "resetClient"}
        await asyncio.Event().wait()

    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    await coordinator._async_update_data()
    assert await connections.get() is None
    assert coordinator._last_event_id == "test-event-1"
    reset.set()
    assert await asyncio.wait_for(connections.get(), 3) is None
    assert "resetClient; discarding the replay cursor" in str(
        coordinator.last_exception
    )
    assert "reconnecting automatically" in str(coordinator.last_exception)
    await coordinator.async_shutdown()


@pytest.mark.parametrize("value", [None, True, "21.5", float("inf"), float("nan")])
def test_invalid_temperature_is_unknown(hass, snapshot, value):
    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.data.devices["test-device"]["attributes"]["temperature"]["value"] = (
        value
    )
    sensor = EvaSensor(coordinator, "test-device", DESCRIPTIONS[0])
    assert sensor.native_value is None
