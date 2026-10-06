"""All 117 SSE names/fields in home-hla-docs/#events-event-types (2026-10-06)."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from custom_components.eva.events import EVENT_TYPE, event_data
from tests.test_coordinator import make_coordinator

CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "sse_events.json").read_text()
)


@pytest.mark.parametrize("event_type", CONTRACT)
async def test_every_documented_sse_event_reaches_automations(
    hass, snapshot, event_type
):
    """Snapshots still replace state; every business event also reaches the bus."""
    event = {
        "eventType": event_type,
        "id": "next-event",
        **{
            field: value
            for field, value in {
                "deviceId": "test-device",
                "deviceName": "Test thermometer",
                "actionId": "test-action",
                "groupId": 1,
                "moodId": "test-mood",
                "name": "temperature",
                "value": 17,
                "activeProfile": {"mode": "armed"},
                "activeMoods": ["test-mood"],
                "softwareUpdate": {"status": "assigned", "version": "2"},
                "automaticSoftwareUpdates": True,
                "warnings": [{"id": "test-warning", "type": "serviceExpired"}],
                "alert": "test-alert",
            }.items()
            if field in CONTRACT[event_type]["fields"]
        },
    }
    # The table omits attribute-report fields; these use the attribute protocol.
    if event_type == "deviceAttributeReport":
        event.update(deviceId="test-device", name="temperature", value=17)
    if CONTRACT[event_type]["home"]:
        event["home"] = deepcopy(snapshot["home"])
        event["home"]["rooms"][0]["devices"][0]["attributes"][0]["value"] = 17
    snapshot["home"]["moods"] = [{"id": "test-mood", "name": "Test mood"}]
    snapshot["home"]["rooms"][0]["groups"] = [
        {"id": 1, "online": True, "attributes": [{"name": "temperature", "value": 20}]}
    ]
    queue = asyncio.Queue()

    async def stream(*args):
        yield snapshot
        yield event
        await asyncio.Event().wait()

    @callback
    def receive(received):
        queue.put_nowait(received.data)

    unsub = hass.bus.async_listen(EVENT_TYPE, receive)
    coordinator = make_coordinator(hass, stream)
    await coordinator._async_setup()
    try:
        received = await asyncio.wait_for(queue.get(), 2)
        assert received["eventType"] == event_type
        assert received["id"] == "next-event"
        assert received["config_entry_id"] == coordinator.config_entry.entry_id
        assert received["home_id"] == "test-home"
        assert "home" not in received
        assert coordinator._last_event_id == "next-event"
        assert coordinator.last_update_success
        if CONTRACT[event_type]["home"]:
            assert (
                coordinator.data.devices["test-device"]["attributes"]["temperature"][
                    "value"
                ]
                == 17
            )
        elif event_type in {"deviceAttributeChanged", "deviceAttributeReport"}:
            assert (
                coordinator.data.devices["test-device"]["attributes"]["temperature"][
                    "value"
                ]
                == 17
            )
        elif event_type == "groupAttributeChanged":
            assert (
                coordinator.data.devices["group:1"]["attributes"]["temperature"][
                    "value"
                ]
                == 17
            )
    finally:
        unsub()
        await coordinator.async_shutdown()


def test_event_bus_omits_private_and_unknown_payloads():
    event = {
        "eventType": "doorLockAccessUpdated",
        "home": {"users": [{"pin": "1234"}]},
        "userEmail": "test@example.invalid",
        "homeUserId": "private-user",
        "rfid": "private-tag",
        "doorLockAccessLabel": "Private label",
        "pin": "1234",
        "futureField": {"secret": "private"},
        "value": {"pin": "1234"},
        "softwareUpdate": {"status": "assigned", "secret": "private"},
        "warnings": [
            {
                "id": "warning",
                "severity": "critical",
                "description": "private",
                "properties": {"pin": "1234"},
            }
        ],
    }
    assert event_data(event) == {
        "eventType": "doorLockAccessUpdated",
        "softwareUpdate": {"status": "assigned"},
        "warnings": [{"id": "warning", "severity": "critical"}],
    }


@pytest.mark.parametrize(
    "outcome",
    [
        "doorLockAccessPinCollision",
        "doorLockAccessTagCollision",
        "doorLockAccessNoAvailableSlot",
        "doorLockFailedAuthPin",
        "scanCanceled",
        "groupSaved",
        "ruleSaved",
        "timelineItemDeleted",
        "deviceEnergySaverEnabled",
    ],
)
async def test_action_outcomes_and_pending_events(hass, snapshot, outcome):
    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.last_update_success = True

    async def command(*args):
        for listener in coordinator._command_listeners:
            listener({"eventType": "deviceAttributeSent", "actionId": "test-action"})
            listener({"eventType": outcome, "actionId": "test-action"})
        return "test-action"

    coordinator.client.async_command = AsyncMock(side_effect=command)
    if outcome in {
        "groupSaved",
        "ruleSaved",
        "timelineItemDeleted",
        "deviceEnergySaverEnabled",
    }:
        await coordinator.async_command("POST", ("devices", "test-device", "identify"))
    else:
        with pytest.raises(HomeAssistantError, match="could not complete"):
            await coordinator.async_command(
                "POST", ("devices", "test-device", "identify")
            )
    assert not coordinator._command_listeners
