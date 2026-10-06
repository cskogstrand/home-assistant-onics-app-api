"""Exercise reconnects, failure states and cancellation without network access."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
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


async def test_initial_auth_failure_stops_stream(hass):
    async def stream(*args):
        raise EvaAuthError("rejected")
        yield  # Make this an async generator, like the real transport.

    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.last_update_success
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


async def test_silent_connection_becomes_unavailable(hass, snapshot):
    closed = asyncio.Event()

    async def stream(*args):
        try:
            yield snapshot
            await asyncio.Event().wait()
        finally:
            closed.set()

    coordinator = make_coordinator(hass, stream)
    with patch("custom_components.eva.coordinator.STREAM_IDLE_TIMEOUT", 0.01):
        await coordinator._async_setup()
        await coordinator._async_update_data()
        await asyncio.wait_for(closed.wait(), 1)
    assert not coordinator.last_update_success
    await coordinator.async_shutdown()


async def test_kill_client_stops_without_retrying_setup(hass):
    async def stream(*args):
        yield {"eventType": "killClient"}

    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    with pytest.raises(ConfigEntryError):
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
