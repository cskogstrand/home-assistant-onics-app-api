"""Exercise native HA platforms with invented devices and confirmed SSE writes."""

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.eva.capabilities import (
    ATTRIBUTES,
    limits,
    platform_for,
    validate_value,
)
from custom_components.eva.const import DOMAIN
from tests.test_init import make_entry


def device(device_id, values, **metadata):
    return {
        "id": device_id,
        "name": str(device_id),
        "online": True,
        "attributes": [
            {
                "name": key,
                "value": value,
                **(
                    {"minValue": 2000, "maxValue": 6500}
                    if key == "colorTemperature"
                    else {}
                ),
            }
            for key, value in values.items()
        ],
        **metadata,
    }


def entity_id(hass, domain, key):
    return er.async_get(hass).async_get_entity_id(
        domain, DOMAIN, f"test:test-home:{key}"
    )


async def test_native_platforms_commands_updates_and_cleanup(hass, snapshot):
    snapshot["home"]["rooms"][0]["devices"] = [
        device(
            "lamp",
            {
                "on": True,
                "dimLevel": 50,
                "colorTemperature": 2700,
                "colorHue": 180,
                "colorSaturation": 50,
                "colorMode": "hsv",
            },
        ),
        device("simple-lamp", {"on": False}, type="lightOnOff"),
        device(
            "plug",
            {
                "on": False,
                "acPower": 123.5,
                "electricityConsumptionSummary": 1000,
                "startupOnOff": "off",
                "onTime": 60,
            },
            supportsIdentify=True,
        ),
        device(
            "thermostat",
            {
                "on": True,
                "setpoint": 21,
                "airTemperature": 20.5,
                "floorTemperature": 24,
                "heating": True,
                "sensor": "floorTemperature",
                "childLock": False,
                "temperatureCalibration": 0,
                "displayText": "Hello",
            },
        ),
        device(
            "cover", {"windowCoverLiftPercentage": 20, "windowCoverTiltPercentage": 80}
        ),
        device(
            "door",
            {
                "locked": True,
                "open": False,
                "boltJammed": False,
                "lowBattery": False,
                "batteryPercentage": 80,
            },
        ),
        device(
            "safety",
            {
                "movement": True,
                "fireIndication": False,
                "waterOverflowIndication": False,
                "co2Concentration": 650,
                "relativeHumidity": 45,
                "pressure": 101325,
                "illuminance": 120,
            },
        ),
        device(
            "firmware",
            {},
            softwareVersion="1.0",
            softwareUpdate={"status": "available", "version": "1.1"},
        ),
        device("future", {"unrecognized": 42, "unrecognizedFlag": False}),
        device("empty", {}),
    ]
    thermostat = snapshot["home"]["rooms"][0]["devices"][3]
    next(a for a in thermostat["attributes"] if a["name"] == "sensor")["options"] = [
        "airTemperature",
        "floorTemperature",
    ]
    snapshot["home"]["rooms"][0]["groups"] = [device(1, {"on": True, "dimLevel": 70})]
    snapshot["home"]["moods"] = [{"id": "evening", "name": "Evening"}]
    snapshot["home"]["activeProfile"] = {"mode": "disarmed"}
    snapshot["home"]["settings"] = {"alarm": {"pinRequired": True}}
    queue = asyncio.Queue()
    writes = []

    async def stream(*args):
        yield snapshot
        while True:
            yield await queue.get()

    async def command(client, home_id, method, parts, payload=None):
        assert home_id == "test-home"
        writes.append((method, parts, payload))
        action_id = f"action-{len(writes)}"
        event = {"actionId": action_id}
        if parts[0] in {"devices", "groups"} and parts[2] == "attributes":
            key, raw_value = parts[3:]
            import json

            try:
                value = json.loads(raw_value)
            except ValueError:
                value = raw_value
            group = parts[0] == "groups"
            event.update(
                eventType="groupAttributeChanged"
                if group
                else "deviceAttributeChanged",
                name=key,
                value=value,
            )
            event["groupId" if group else "deviceId"] = (
                int(parts[1]) if group else parts[1]
            )
        elif parts[-1] == "identify":
            event.update(eventType="deviceIdentified", deviceId=parts[1])
        elif parts[-1] == "updateSoftware":
            event.update(
                eventType="deviceSoftwareUpdateAssigned",
                deviceId=parts[1],
                softwareUpdate={"status": "assigned", "version": "1.1"},
            )
        elif parts[0] == "moods":
            event.update(eventType="moodActivated")
        else:
            event.update(
                eventType="activeProfileUpdated",
                activeProfile={"mode": payload["mode"]},
            )
        queue.put_nowait(event)
        return action_id

    entry = make_entry(hass)
    with (
        patch("custom_components.eva.api.EvaClient.async_events", new=stream),
        patch("custom_components.eva.api.EvaClient.async_command", new=command),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        for domain, key, expected in [
            ("light", "lamp:light", "on"),
            ("light", "simple-lamp:light", "off"),
            ("switch", "plug:on", "off"),
            ("sensor", "plug:acPower", "123.5"),
            ("sensor", "plug:electricityConsumptionSummary", "1000"),
            ("climate", "thermostat:setpoint", "heat"),
            ("cover", "cover:cover", "open"),
            ("lock", "door:locked", "locked"),
            ("binary_sensor", "door:open", "off"),
            ("binary_sensor", "safety:movement", "on"),
            ("sensor", "safety:relativeHumidity", "45"),
            ("number", "thermostat:temperatureCalibration", "0"),
            ("text", "thermostat:displayText", "Hello"),
            ("select", "thermostat:sensor", "floorTemperature"),
            ("update", "firmware:firmware", "on"),
            ("sensor", "future:unrecognized", "42"),
            ("sensor", "future:unrecognizedFlag", "false"),
            ("alarm_control_panel", "alarm", "disarmed"),
            ("light", "group:1:light", "on"),
        ]:
            state = hass.states.get(entity_id(hass, domain, key))
            assert state is not None, (domain, key)
            assert state.state == expected, (key, state)
        assert (
            hass.states.get(entity_id(hass, "light", "lamp:light")).attributes[
                "brightness"
            ]
            == 128
        )
        assert (
            hass.states.get(
                entity_id(hass, "climate", "thermostat:setpoint")
            ).attributes["current_temperature"]
            == 24
        )
        assert (
            hass.states.get(entity_id(hass, "cover", "cover:cover")).attributes[
                "current_position"
            ]
            == 80
        )
        assert (
            hass.states.get(
                entity_id(hass, "sensor", "plug:electricityConsumptionSummary")
            ).attributes["state_class"]
            == "total_increasing"
        )
        assert dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, "test:test-home:empty"), entry.entry_id
        )
        assert entity_id(hass, "switch", "thermostat:on") is None
        assert entity_id(hass, "switch", "lamp:on") is None

        for domain, service, key, data, expected_parts in [
            (
                "switch",
                "turn_on",
                "plug:on",
                {},
                ("devices", "plug", "attributes", "on", "true"),
            ),
            (
                "light",
                "turn_on",
                "lamp:light",
                {"brightness": 255, "hs_color": [90, 25]},
                ("devices", "lamp", "attributes", "on", "true"),
            ),
            (
                "light",
                "turn_off",
                "simple-lamp:light",
                {},
                ("devices", "simple-lamp", "attributes", "on", "false"),
            ),
            (
                "climate",
                "set_temperature",
                "thermostat:setpoint",
                {"temperature": 23},
                ("devices", "thermostat", "attributes", "setpoint", "23"),
            ),
            (
                "climate",
                "set_hvac_mode",
                "thermostat:setpoint",
                {"hvac_mode": "off"},
                ("devices", "thermostat", "attributes", "on", "false"),
            ),
            (
                "cover",
                "set_cover_position",
                "cover:cover",
                {"position": 10},
                ("devices", "cover", "attributes", "windowCoverLiftPercentage", "90"),
            ),
            (
                "cover",
                "set_cover_tilt_position",
                "cover:cover",
                {"tilt_position": 30},
                ("devices", "cover", "attributes", "windowCoverTiltPercentage", "70"),
            ),
            (
                "lock",
                "unlock",
                "door:locked",
                {},
                ("devices", "door", "attributes", "locked", "false"),
            ),
            (
                "number",
                "set_value",
                "thermostat:temperatureCalibration",
                {"value": 0.5},
                (
                    "devices",
                    "thermostat",
                    "attributes",
                    "temperatureCalibration",
                    "0.5",
                ),
            ),
            (
                "select",
                "select_option",
                "thermostat:sensor",
                {"option": "airTemperature"},
                ("devices", "thermostat", "attributes", "sensor", "airTemperature"),
            ),
            (
                "text",
                "set_value",
                "thermostat:displayText",
                {"value": "Welcome"},
                ("devices", "thermostat", "attributes", "displayText", "Welcome"),
            ),
            ("button", "press", "plug:identify", {}, ("devices", "plug", "identify")),
            (
                "update",
                "install",
                "firmware:firmware",
                {},
                ("devices", "firmware", "updateSoftware"),
            ),
            ("scene", "turn_on", "mood:evening", {}, ("moods", "evening", "activate")),
            (
                "alarm_control_panel",
                "alarm_arm_night",
                "alarm",
                {"code": "0123"},
                ("profiles", "active"),
            ),
            (
                "light",
                "turn_off",
                "group:1:light",
                {},
                ("groups", "1", "attributes", "on", "false"),
            ),
        ]:
            await hass.services.async_call(
                domain,
                service,
                {"entity_id": entity_id(hass, domain, key), **data},
                blocking=True,
            )
            assert writes[-1][1] == expected_parts
        assert writes[-1][0] == "POST"
        assert (
            hass.states.get(entity_id(hass, "lock", "door:locked")).state == "unlocked"
        )
        assert (
            hass.states.get(entity_id(hass, "alarm_control_panel", "alarm")).state
            == "armed_night"
        )
        assert (
            hass.states.get(entity_id(hass, "update", "firmware:firmware")).attributes[
                "in_progress"
            ]
            is True
        )
        queue.put_nowait(
            {
                "eventType": "activeProfileUpdated",
                "activeProfile": {"mode": "armed"},
                "estimatedExitDelayExpiresAt": "2099-01-01T00:00:00Z",
            }
        )
        await hass.async_block_till_done()
        assert (
            hass.states.get(entity_id(hass, "alarm_control_panel", "alarm")).state
            == "arming"
        )
        queue.put_nowait(
            {
                "eventType": "activeProfileExitTimeExpired",
                "activeProfile": {"mode": "armed"},
            }
        )
        await hass.async_block_till_done()
        assert (
            hass.states.get(entity_id(hass, "alarm_control_panel", "alarm")).state
            == "armed_away"
        )
        queue.put_nowait(
            {
                "eventType": "activeProfileEntryTimeStarted",
                "estimatedEntryDelayExpiresAt": "2099-01-01T00:00:00Z",
            }
        )
        queue.put_nowait(
            {
                "eventType": "deviceSoftwareUpdateInProgress",
                "deviceId": "firmware",
                "softwareUpdate": {"progress": 50, "status": "inProgress"},
            }
        )
        await hass.async_block_till_done()
        assert (
            hass.states.get(entity_id(hass, "alarm_control_panel", "alarm")).state
            == "pending"
        )
        assert (
            hass.states.get(entity_id(hass, "update", "firmware:firmware")).attributes[
                "update_percentage"
            ]
            == 50
        )
        before = len(writes)
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "alarm_control_panel",
                "alarm_disarm",
                {"entity_id": entity_id(hass, "alarm_control_panel", "alarm")},
                blocking=True,
            )
        queue.put_nowait({"eventType": "deviceEnergySaverEnabled", "deviceId": "plug"})
        await hass.async_block_till_done()
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "switch",
                "turn_off",
                {"entity_id": entity_id(hass, "switch", "plug:on")},
                blocking=True,
            )
        assert len(writes) == before
        queue.put_nowait({"eventType": "deviceEnergySaverDisabled", "deviceId": "plug"})
        queue.put_nowait(
            {"eventType": "activeMoodsChanged", "activeMoods": ["evening"]}
        )
        await hass.async_block_till_done()
        await hass.services.async_call(
            "switch",
            "turn_off",
            {"entity_id": entity_id(hass, "switch", "plug:on")},
            blocking=True,
        )
        assert len(writes) == before + 1
        scene_id = entity_id(hass, "scene", "mood:evening")
        assert hass.states.get(scene_id).attributes["active"] is True
        queue.put_nowait({"eventType": "activeMoodsChanged", "activeMoods": []})
        await hass.async_block_till_done()
        assert hass.states.get(scene_id).attributes["active"] is False

        queue.put_nowait(
            {
                "eventType": "deviceAttributeChanged",
                "deviceId": "safety",
                "name": "tampered",
                "value": True,
            }
        )
        await hass.async_block_till_done()
        assert (
            hass.states.get(entity_id(hass, "binary_sensor", "safety:tampered")).state
            == "on"
        )
        queue.put_nowait({"eventType": "deviceOffline", "deviceId": "door"})
        await hass.async_block_till_done()
        assert (
            hass.states.get(entity_id(hass, "lock", "door:locked")).state
            == "unavailable"
        )
        assert (
            hass.states.get(entity_id(hass, "binary_sensor", "door:open")).state
            == "unavailable"
        )
        removed_id = entity_id(hass, "light", "lamp:light")
        queue.put_nowait({"eventType": "deviceDeleted", "deviceId": "lamp"})
        await hass.async_block_till_done()
        assert hass.states.get(removed_id) is None
        removed_scene = entity_id(hass, "scene", "mood:evening")
        replacement = deepcopy(snapshot)
        replacement["home"]["moods"] = []
        queue.put_nowait(replacement)
        await hass.async_block_till_done()
        assert hass.states.get(removed_scene) is None
        coordinator = entry.runtime_data
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert not coordinator._command_listeners


@pytest.mark.parametrize(
    "key,value",
    [
        ("on", 1),
        ("temperature", 22),
        ("onTime", -2),
        ("onTime", float("nan")),
        ("onTime", True),
        ("dimLevel", 0),
        ("startupOnOff", "unsupported"),
        ("displayText", "x" * 15),
        ("unknown", True),
        ("powerLevel", 3),
    ],
)
def test_writes_reject_invalid_and_read_only_attributes(key, value):
    data = {"attributes": {key: {"value": None}}}
    with pytest.raises(ValueError):
        validate_value(data, key, value)


def test_dynamic_bounds_options_and_thermostat_calibration():
    data = {
        "attributes": {
            "chargeCurrent": {"minValue": 6, "maxValue": 32, "step": 2},
            "sensor": {"options": ["floorTemperature"]},
            "setpoint": {},
            "temperatureCalibration": {},
        }
    }
    assert limits(data, "chargeCurrent") == (6, 32, 2)
    assert validate_value(data, "chargeCurrent", 8) == 8
    assert validate_value(data, "temperatureCalibration", 0.5) == 0.5
    data["attributes"]["setpoint"] = {"minValue": 5, "maxValue": 30, "step": 0.5}
    assert validate_value(data, "setpoint", 20.5) == 20.5
    for key, value in [
        ("chargeCurrent", 7),
        ("chargeCurrent", 33),
        ("sensor", "airTemperature"),
    ]:
        with pytest.raises(ValueError):
            validate_value(data, key, value)
    data["attributes"]["chargeCurrent"] = {}
    data["attributes"]["sensor"] = {}
    assert platform_for(data, "chargeCurrent") == "sensor"
    assert platform_for(data, "sensor") == "sensor"
    for key in ATTRIBUTES:
        assert platform_for({"attributes": {key: {}}}, key) in {
            "sensor",
            "binary_sensor",
            "switch",
            "light",
            "cover",
            "climate",
            "lock",
            "number",
            "select",
            "text",
        }


@pytest.mark.parametrize(
    "outcome",
    [
        "deviceAttributeChanged",
        "actionTimeout",
        "deviceAttributeUpdateFailed",
        "doorLockFailedAuthPin",
    ],
)
async def test_command_handles_early_confirmation_and_failure(hass, snapshot, outcome):
    from unittest.mock import AsyncMock

    from tests.test_coordinator import make_coordinator

    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.last_update_success = True

    async def command(*args):
        for listener in coordinator._command_listeners:
            listener({"eventType": outcome, "actionId": "test-action"})
        return "test-action"

    coordinator.client.async_command = AsyncMock(side_effect=command)
    if outcome == "deviceAttributeChanged":
        await coordinator.async_command(
            "PATCH", ("devices", "test-device", "attributes", "on", "true")
        )
    else:
        with pytest.raises(HomeAssistantError):
            await coordinator.async_command(
                "PATCH", ("devices", "test-device", "attributes", "on", "true")
            )
    assert not coordinator._command_listeners


async def test_external_charger_polling_controls_and_unload(hass, snapshot):
    from unittest.mock import AsyncMock

    from custom_components.eva.api import EvaError

    snapshot["home"]["rooms"][0]["devices"] = [
        device("ev", {}, external=True, type="evCharger")
    ]
    # External chargers are cloud-connected independently of the Zigbee gateway.
    snapshot["home"]["gateway"]["online"] = False
    queue = asyncio.Queue()

    async def stream(*args):
        yield snapshot
        while True:
            yield await queue.get()

    entry = make_entry(hass)
    with (
        patch("custom_components.eva.api.EvaClient.async_events", new=stream),
        patch(
            "custom_components.eva.api.EvaClient.async_get_charger_status",
            new_callable=AsyncMock,
            return_value={"carPluggedIn": True, "charging": False, "currentPower": 0},
        ) as status,
        patch(
            "custom_components.eva.api.EvaClient.async_command",
            new_callable=AsyncMock,
            return_value=None,
        ) as command,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        coordinator = entry.runtime_data
        charging_id = entity_id(hass, "switch", "ev:charging")
        assert hass.states.get(charging_id).state == "off"
        assert (
            hass.states.get(entity_id(hass, "binary_sensor", "ev:carPluggedIn")).state
            == "on"
        )
        assert (
            hass.states.get(entity_id(hass, "sensor", "ev:currentPower")).state == "0"
        )
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": charging_id}, blocking=True
        )
        command.assert_awaited_once_with(
            "test-home",
            "POST",
            ("devices", "ev", "external", "evCharger", "start"),
            None,
        )
        assert (
            hass.states.get(charging_id).state == "off"
        )  # HTTP acceptance is not a state report.
        coordinator._charger_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await coordinator._charger_task
        status.side_effect = EvaError("offline")
        coordinator._charger_task = hass.async_create_background_task(
            coordinator._async_poll_chargers(), "test poll"
        )
        await hass.async_block_till_done()
        assert hass.states.get(charging_id).state == "unavailable"
        assert (
            hass.states.get(entity_id(hass, "sensor", "ev:currentPower")).state
            == "unavailable"
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert coordinator._charger_task is None


async def test_command_cancellation_and_auth_failure(hass, snapshot):
    from unittest.mock import AsyncMock

    from custom_components.eva.api import EvaAuthError
    from tests.test_coordinator import make_coordinator

    coordinator = make_coordinator(hass, None)
    coordinator.data = coordinator.data.apply(snapshot)
    coordinator.last_update_success = True
    coordinator.client.async_command = AsyncMock(return_value="pending")
    task = hass.async_create_background_task(
        coordinator.async_command("POST", ("devices", "test-device", "identify")),
        "command test",
    )
    await hass.async_block_till_done()
    assert coordinator._command_listeners
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not coordinator._command_listeners
    coordinator.client.async_command.side_effect = EvaAuthError("rejected")
    with patch.object(type(coordinator.config_entry), "async_start_reauth") as reauth:
        with pytest.raises(HomeAssistantError):
            await coordinator.async_command(
                "POST", ("devices", "test-device", "identify")
            )
        reauth.assert_called_once_with(hass)
    assert not coordinator._command_listeners
