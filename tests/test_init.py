"""Verify the real HA entry lifecycle with sanitized, in-memory SSE events."""

import asyncio
from unittest.mock import patch

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eva.api import EvaAuthError, EvaError
from custom_components.eva.const import DOMAIN


def make_entry(hass, environment="test"):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{environment}:test-home",
        title="Test home",
        data={
            "environment": environment,
            "username": "test@example.invalid",
            "password": "test-password",
            "home_id": "test-home",
            "sse_client_id": "test-client",
        },
    )
    entry.add_to_hass(hass)
    return entry


async def test_real_setup_sensor_updates_environment_identity_and_unload(
    hass, snapshot
):
    queue = asyncio.Queue()
    closed = []

    async def stream(client, home_id, client_id, last_seen_event_id=None):
        assert home_id == "test-home"
        assert client_id == "test-client"
        assert client._headers["Authorization"] == aiohttp.encode_basic_auth(
            "test@example.invalid", "test-password"
        )
        try:
            yield snapshot
            while True:
                yield await queue.get()
        finally:
            closed.append(client._base_url)

    entry = make_entry(hass)
    with (
        patch("custom_components.eva.api.EvaClient.async_events", new=stream),
        patch(
            "custom_components.eva.async_create_clientsession",
            wraps=async_create_clientsession,
        ) as sessions,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
        coordinator = entry.runtime_data
        test_session = coordinator.client._session
        assert sessions.call_count == 1
        registry = er.async_get(hass)
        entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, "test:test-home:test-device:temperature"
        )
        assert hass.states.get(entity_id).state == "21.5"
        assert hass.states.get(entity_id).attributes["unit_of_measurement"] == "°C"

        queue.put_nowait(
            {
                "eventType": "deviceAttributeChanged",
                "deviceId": "test-device",
                "name": "temperature",
                "value": 22.75,
                "id": "test-update",
            }
        )
        await hass.async_block_till_done()
        assert hass.states.get(entity_id).state == "22.75"

        other_entry = make_entry(hass, "prod")
        assert await hass.config_entries.async_setup(other_entry.entry_id)
        await hass.async_block_till_done()
        other_entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, "prod:test-home:test-device:temperature"
        )
        assert other_entity_id != entity_id
        assert hass.states.get(other_entity_id).state == "21.5"
        devices = dr.async_get(hass)
        assert (
            devices.async_get_device_by_identifier(
                (DOMAIN, "test:test-home:test-device"),
                entry.entry_id,
            ).id
            != devices.async_get_device_by_identifier(
                (DOMAIN, "prod:test-home:test-device"),
                other_entry.entry_id,
            ).id
        )

        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert coordinator._task is None
        assert test_session.closed
        assert hass.states.get(entity_id).state == "unavailable"
        assert hass.states.get(other_entity_id).state == "21.5"
        assert await hass.config_entries.async_unload(other_entry.entry_id)
        assert len(closed) == 2


async def test_setup_auth_failure_prompts_reauthentication_and_cleans_up(hass):
    clients = []

    async def stream(client, *args):
        clients.append(client)
        raise EvaAuthError("rejected")
        yield

    entry = make_entry(hass)
    with patch("custom_components.eva.api.EvaClient.async_events", new=stream):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert clients[0]._session.closed
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["step_id"] == "reauth_confirm"
    assert not hass.states.async_entity_ids("sensor")


async def test_setup_connection_failure_retries_and_cleans_up(hass):
    clients = []

    async def stream(client, *args):
        clients.append(client)
        raise EvaError("offline")
        yield

    entry = make_entry(hass)
    with (
        patch("custom_components.eva.api.EvaClient.async_events", new=stream),
        patch("custom_components.eva.coordinator.INITIAL_SNAPSHOT_TIMEOUT", 0.01),
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert clients[0]._session.closed
    assert not hass.states.async_entity_ids("sensor")
    await hass.config_entries.async_unload(entry.entry_id)
