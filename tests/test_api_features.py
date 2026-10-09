"""Missing API capabilities, using only invented homes and in-memory requests."""

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest
import voluptuous as vol
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.eva.api import EvaAuthError, EvaError
from custom_components.eva.events import event_data
from custom_components.eva.services import SCHEMAS
from custom_components.eva.state import HomeState, InvalidEvent
from tests.test_init import make_entry
from tests.test_platforms import device, entity_id


def test_alarm_countdowns_survive_snapshots_and_reconstruct_after_restart(snapshot):
    home = snapshot["home"]
    home["activeProfile"] = {"mode": "armed", "modeChangedAt": "2099-01-01T00:00:00Z"}
    home["profiles"] = {"armed": {"exitDuration": 45}}
    state = HomeState("test-home", {}, False).apply(snapshot)
    assert state.alarm["exit_at"] == "2099-01-01T00:00:45+00:00"
    state = state.apply(
        {
            "eventType": "activeProfileEntryTimeStarted",
            "estimatedEntryDelayExpiresAt": "2099-01-01T01:00:00Z",
        }
    )
    updated = state.apply({"eventType": "deviceUpdated", "home": deepcopy(home)})
    assert updated.alarm == state.alarm
    home["activeProfile"]["modeChangedAt"] = "2099-01-02T00:00:00Z"
    changed = state.apply(snapshot)
    assert "entry_at" not in changed.alarm
    assert changed.alarm["exit_at"] == "2099-01-02T00:00:45+00:00"
    home["activeProfile"]["mode"] = "disarmed"
    assert "entry_at" not in state.apply(snapshot).alarm
    assert "exit_at" not in state.apply(snapshot).alarm
    for bad_date in (None, "invalid", "2099-01-01T00:00:00"):
        home["activeProfile"] = {"mode": "armed", "modeChangedAt": bad_date}
        assert "exit_at" not in HomeState("test-home", {}, False).apply(snapshot).alarm


def test_safe_operational_event_details():
    assert event_data(
        {
            "eventType": "cameraProvisioningQrCreated",
            "value": "invented-secret",
            "deviceId": "camera",
        }
    ) == {"eventType": "cameraProvisioningQrCreated", "deviceId": "camera"}
    assert "value" not in event_data(
        {"eventType": "futureCredentialEvent", "value": "secret"}
    )
    assert event_data(
        {
            "eventType": "cameraMotionDetected",
            "value": {
                "kind": "PERSON",
                "state": "START",
                "detectedAt": "2099-01-01T00:00:00Z",
                "private": "secret",
            },
        }
    )["value"] == {
        "kind": "PERSON",
        "state": "START",
        "detectedAt": "2099-01-01T00:00:00Z",
    }
    assert event_data(
        {
            "eventType": "homeEventCreated",
            "homeEvent": {
                "id": "log-1",
                "iconType": "doorUnlockedKeypad",
                "title": "Private name",
                "bodyText": "Private home",
            },
        }
    )["homeEvent"] == {"id": "log-1", "iconType": "doorUnlockedKeypad"}
    assert event_data(
        {
            "eventType": "gatewayAutomaticSoftwareUpdatesSaved",
            "automaticSoftwareUpdates": {
                "enabled": True,
                "hourOfDay": 12,
                "secret": "hidden",
            },
        }
    )["automaticSoftwareUpdates"] == {"enabled": True, "hourOfDay": 12}


@pytest.fixture
async def runtime(hass, snapshot, saved_credentials):
    snapshot["home"]["gateway"].update(
        id="gateway-1",
        name="Test gateway",
        softwareVersion="1",
        softwareUpdate={"status": "available", "version": "2"},
        automaticSoftwareUpdates={"enabled": True, "hourOfDay": 12},
    )
    snapshot["home"]["rooms"][0]["devices"] = [
        device("lamp", {"on": True, "dimLevel": 20}),
        device("plug", {"on": True}),
        device("lock", {"locked": True}, vendor="Danalock", model="V3 BTZBE"),
        device(
            "heater",
            {"setpoint": 20},
            eligibleForEnergySaver=True,
            energySaverEnabled=True,
            externalDeviceId="external-heater",
        ),
        device(
            "new-heater",
            {"setpoint": 20},
            eligibleForEnergySaver=True,
            energySaverEnabled=False,
        ),
        device(
            "charger",
            {},
            external=True,
            type="evCharger",
            externalDeviceId="external-charger",
        ),
    ]
    snapshot["home"]["moods"] = [{"id": "evening", "name": "Evening"}]
    snapshot["home"]["groups"] = [
        {"id": 7, "name": "Lights", "deviceIds": ["lamp", "plug"]}
    ]
    queue = asyncio.Queue()

    async def stream(*args):
        yield {
            "eventType": "homeFeatures",
            "homeFeatures": {
                "groups": {"enabled": True},
                "doorLock": {"enabled": True},
            },
        }
        yield snapshot
        while True:
            yield await queue.get()

    entry = make_entry(hass)
    with (
        patch("custom_components.eva.api.EvaClient.async_events", new=stream),
        patch(
            "custom_components.eva.api.EvaClient.async_command",
            new_callable=AsyncMock,
            return_value=None,
        ) as command,
        patch(
            "custom_components.eva.api.EvaClient.async_get_data",
            new_callable=AsyncMock,
            return_value={"result": "test"},
        ) as read,
        patch(
            "custom_components.eva.api.EvaClient.async_get_charger_status",
            new_callable=AsyncMock,
            return_value={"charging": False, "carPluggedIn": True, "currentPower": 0},
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, queue, command, read
        await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_gateway_entities_commands_and_updates(hass, runtime):
    _, queue, command, _ = runtime
    gateway = "gateway:gateway-1:"
    assert (
        hass.states.get(
            entity_id(hass, "binary_sensor", gateway + "gatewayOnline")
        ).state
        == "on"
    )
    assert (
        hass.states.get(entity_id(hass, "update", gateway + "firmware")).state == "on"
    )
    for domain, action, key, data, parts, payload in [
        ("button", "press", "ping", {}, ("gateway", "ping"), None),
        ("update", "install", "firmware", {}, ("gateway", "updateSoftware"), None),
    ]:
        await hass.services.async_call(
            domain,
            action,
            {"entity_id": entity_id(hass, domain, gateway + key), **data},
            blocking=True,
        )
        assert command.call_args.args[2:] == (parts, payload)
    assert (
        hass.states.get(entity_id(hass, "sensor", gateway + "gatewayUpdateHour")).state
        == "12"
    )
    assert (
        hass.states.get(
            entity_id(hass, "binary_sensor", gateway + "gatewayAutomaticUpdates")
        ).state
        == "on"
    )
    queue.put_nowait(
        {
            "eventType": "gatewayAutomaticSoftwareUpdatesSaved",
            "automaticSoftwareUpdates": {"enabled": False, "hourOfDay": 9},
        }
    )
    queue.put_nowait(
        {
            "eventType": "gatewaySoftwareUpdateInProgress",
            "softwareUpdate": {"status": "inProgress", "version": "2"},
        }
    )
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id(hass, "sensor", gateway + "gatewayUpdateHour")).state
        == "9"
    )
    assert (
        hass.states.get(
            entity_id(hass, "binary_sensor", gateway + "gatewayAutomaticUpdates")
        ).state
        == "off"
    )
    assert (
        hass.states.get(entity_id(hass, "update", gateway + "firmware")).attributes[
            "in_progress"
        ]
        is True
    )
    queue.put_nowait({"eventType": "gatewayOffline"})
    await hass.async_block_till_done()
    assert (
        hass.states.get(
            entity_id(hass, "binary_sensor", gateway + "gatewayOnline")
        ).state
        == "off"
    )
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": entity_id(hass, "button", gateway + "ping")},
        blocking=True,
    )
    command.assert_awaited_with("test-home", "POST", ("gateway", "ping"), None)


async def test_pin_unlock_and_home_feature_gates(hass, runtime):
    entry, queue, command, _ = runtime
    lock = entity_id(hass, "lock", "lock:locked")
    await hass.services.async_call(
        "lock", "unlock", {"entity_id": lock, "code": "0123"}, blocking=True
    )
    command.assert_awaited_with(
        "test-home",
        "PATCH",
        ("devices", "lock"),
        {"attributes": [{"name": "locked", "value": False, "authPin": "0123"}]},
    )
    assert hass.states.get(lock).state == "locked"
    command.reset_mock()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "lock", "unlock", {"entity_id": lock, "code": "abc"}, blocking=True
        )
    command.assert_not_awaited()
    queue.put_nowait(
        {
            "eventType": "homeFeatures",
            "homeFeatures": {
                "doorLock": {"enabled": False},
                "moods": {"enabled": False},
            },
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get(lock).state == "unavailable"
    with pytest.raises(HomeAssistantError, match="disabled"):
        await entry.runtime_data.async_command(
            "PATCH", ("devices", "lock", "attributes", "locked", "false")
        )
    with pytest.raises(HomeAssistantError, match="disabled"):
        await entry.runtime_data.async_command("POST", ("moods", "evening", "activate"))
    command.assert_not_awaited()


async def test_group_validation_and_energy_saver_switch(hass, runtime):
    entry, queue, command, _ = runtime
    base = {"config_entry_id": entry.entry_id}
    groups = await hass.services.async_call(
        "eva", "get_groups", base, blocking=True, return_response=True
    )
    assert groups["groups"][0]["id"] == 7
    assert "group:7" not in entry.runtime_data.data.devices
    await hass.services.async_call(
        "eva",
        "set_group_attribute",
        {**base, "group_id": 7, "attribute": "on", "value": False},
        blocking=True,
    )
    command.assert_awaited_with(
        "test-home", "POST", ("groups", "7", "attributes", "on", "false"), None
    )
    command.reset_mock()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "eva",
            "set_group_attribute",
            {**base, "group_id": 7, "attribute": "dimLevel", "value": 50},
            blocking=True,
        )
    command.assert_not_awaited()
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": entity_id(hass, "switch", "heater:energySaverEnabled")},
        blocking=True,
    )
    command.assert_awaited_with(
        "test-home", "PATCH", ("devices", "heater"), {"energySaverEnabled": False}
    )
    assert (
        hass.states.get(entity_id(hass, "switch", "heater:energySaverEnabled")).state
        == "on"
    )
    queue.put_nowait({"eventType": "deviceEnergySaverDisabled", "deviceId": "heater"})
    await hass.async_block_till_done()
    assert (
        hass.states.get(entity_id(hass, "switch", "heater:energySaverEnabled")).state
        == "off"
    )


async def test_pin_unlock_respects_reported_attribute_options(hass, runtime):
    _, queue, command, _ = runtime
    queue.put_nowait(
        {
            "eventType": "deviceAttributeChanged",
            "deviceId": "lock",
            "name": "locked",
            "value": True,
            "options": [True],
        }
    )
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError, match="Unsupported option"):
        await hass.services.async_call(
            "lock",
            "unlock",
            {"entity_id": entity_id(hass, "lock", "lock:locked"), "code": "0123"},
            blocking=True,
        )
    command.assert_not_awaited()


@pytest.mark.parametrize(
    "action,data,method,parts,payload",
    [
        (
            "configure_gateway_updates",
            {"enabled": False, "hour_of_day": 9},
            "PATCH",
            ("gateway", "automaticSoftwareUpdates"),
            {"enabled": False, "hourOfDay": 9},
        ),
        (
            "read_attribute",
            {"device_id": "lamp", "attribute": "dimLevel"},
            "POST",
            ("devices", "lamp", "attributes", "dimLevel", "read"),
            None,
        ),
        (
            "calibrate_lock",
            {"device_id": "lock"},
            "POST",
            ("devices", "lock", "startAutoCalibration"),
            None,
        ),
        (
            "configure_energy_saver",
            {"device_id": "heater", "settings": {"enabled": False}},
            "PATCH",
            ("energySaver", "devices", "external-heater", "settings"),
            {"enabled": False},
        ),
        (
            "configure_energy_saver",
            {"device_id": "new-heater", "settings": {"enabled": True}},
            "POST",
            ("energySaver", "devices", "new-heater", "settings"),
            {"enabled": True},
        ),
        (
            "configure_home_energy_saver",
            {
                "settings": {
                    "away": {"enabled": True, "validFrom": None, "validTo": None}
                }
            },
            "PATCH",
            ("energySaver",),
            {"away": {"enabled": True, "validFrom": None, "validTo": None}},
        ),
        (
            "set_energy_saver_priority",
            {"device_ids": ["heater", "charger"]},
            "PUT",
            ("energySaver", "throttlePriority"),
            {"throttlePriority": ["external-heater", "external-charger"]},
        ),
    ],
)
async def test_home_action_routes(hass, runtime, action, data, method, parts, payload):
    entry, _, command, _ = runtime
    await hass.services.async_call(
        "eva", action, {"config_entry_id": entry.entry_id, **data}, blocking=True
    )
    command.assert_awaited_with("test-home", method, parts, payload)


@pytest.mark.parametrize(
    "action,data,parts,params",
    [
        (
            "get_energy_saver",
            {"kind": "settings", "device_id": "heater"},
            ("energySaver", "devices", "external-heater", "settings"),
            {},
        ),
        (
            "get_energy_saver",
            {"kind": "summary", "device_id": "heater"},
            ("energySaver", "devices", "external-heater", "summary"),
            {},
        ),
        (
            "get_energy_saver",
            {
                "kind": "eventlog",
                "device_id": "heater",
                "start_time_key": "opaque/token",
            },
            ("energySaver", "devices", "external-heater", "eventlog"),
            {"count": 20, "startTimeKey": "opaque/token"},
        ),
        (
            "get_energy_saver",
            {"kind": "priority"},
            ("energySaver", "throttlePriority"),
            {},
        ),
        (
            "get_energy_saver",
            {"kind": "home_eventlog"},
            ("energySaver", "topLevelEventlog"),
            {"count": 20},
        ),
        (
            "get_home_events",
            {"device_id": "lamp", "mood_id": "evening"},
            ("events",),
            {"offset": 0, "count": 100, "deviceId": "lamp", "moodId": "evening"},
        ),
    ],
)
async def test_read_action_routes(hass, runtime, action, data, parts, params):
    entry, _, command, read = runtime
    result = await hass.services.async_call(
        "eva",
        action,
        {"config_entry_id": entry.entry_id, **data},
        blocking=True,
        return_response=True,
    )
    assert result == {"data": {"result": "test"}}
    read.assert_awaited_with("test-home", parts, params)
    command.assert_not_awaited()


@pytest.mark.parametrize(
    "action,extra,parts",
    [
        ("get_energy_saver", {"kind": "prices"}, ("energySaver", "electricityPrices")),
        (
            "get_energy_saver",
            {"kind": "plan", "device_id": "heater"},
            ("energySaver", "devices", "external-heater", "plan"),
        ),
        (
            "get_measurements",
            {
                "device_id": "lamp",
                "attribute": "dimLevel",
                "time_zone": "Europe/Oslo",
                "window_duration": "1h",
            },
            ("devices", "attributes", "measurements"),
        ),
        (
            "get_charger_statistics",
            {"device_id": "charger", "time_zone": "Europe/Oslo"},
            ("devices", "charger", "external", "evCharger", "stats"),
        ),
    ],
)
async def test_historical_queries(hass, runtime, action, extra, parts):
    entry, _, _, read = runtime
    data = {
        "config_entry_id": entry.entry_id,
        "time_start": "2099-01-01T00:00:00Z",
        "time_stop": "2099-01-02T00:00:00Z",
        **extra,
    }
    await hass.services.async_call(
        "eva", action, data, blocking=True, return_response=True
    )
    assert read.call_args.args[1] == parts
    assert read.call_args.args[2]["timeStart"] == data["time_start"]
    assert read.call_args.args[2]["timeStop"] == data["time_stop"]
    read.reset_mock()
    data["time_stop"] = data["time_start"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "eva", action, data, blocking=True, return_response=True
        )
    read.assert_not_awaited()


@pytest.mark.parametrize(
    "action,data",
    [
        ("read_attribute", {"device_id": "not-in-home", "attribute": "on"}),
        ("read_attribute", {"device_id": "lamp", "attribute": "unknown"}),
        ("calibrate_lock", {"device_id": "lamp"}),
        (
            "configure_energy_saver",
            {"device_id": "lamp", "settings": {"enabled": True}},
        ),
        ("get_energy_saver", {"kind": "summary"}),
        ("get_energy_saver", {"kind": "settings", "device_id": "new-heater"}),
        ("get_energy_saver", {"kind": "prices", "device_id": "heater"}),
        ("get_energy_saver", {"kind": "prices"}),
        ("get_home_events", {"mood_id": "unknown"}),
    ],
)
async def test_invalid_actions_never_contact_api(hass, runtime, action, data):
    entry, _, command, read = runtime
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "eva",
            action,
            {"config_entry_id": entry.entry_id, **data},
            blocking=True,
            return_response=action.startswith("get_"),
        )
    command.assert_not_awaited()
    read.assert_not_awaited()


@pytest.mark.parametrize(
    "settings",
    [
        {"enabled": "true"},
        {"maxCurrent": True},
        {"setPoint": float("nan")},
        {"setPoint": 10**400},
        {"readyTime": "25:00"},
        {"overrideUntil": "2099-01-01T00:00:00"},
        {"pin": "1234"},
        {},
    ],
)
def test_energy_saver_rejects_invalid_settings(settings):
    with pytest.raises(vol.Invalid):
        SCHEMAS["configure_energy_saver"](
            {"config_entry_id": "entry", "device_id": "heater", "settings": settings}
        )


async def test_home_actions_require_admin_and_loaded_entry(
    hass, runtime, hass_read_only_user
):
    from homeassistant.core import Context

    entry, _, command, read = runtime
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            "eva",
            "get_groups",
            {"config_entry_id": entry.entry_id},
            blocking=True,
            return_response=True,
            context=Context(user_id=hass_read_only_user.id),
        )
    with pytest.raises(ServiceValidationError, match="loaded Eva"):
        await hass.services.async_call(
            "eva",
            "get_groups",
            {"config_entry_id": "unknown-entry"},
            blocking=True,
            return_response=True,
        )
    command.assert_not_awaited()
    read.assert_not_awaited()


def test_invalid_features_and_groups(snapshot):
    state = HomeState("test-home", {}, False)
    for flags in (None, [], {"moods": {"enabled": "false"}}):
        with pytest.raises(InvalidEvent):
            state.apply({"eventType": "homeFeatures", "homeFeatures": flags})
    snapshot["home"]["groups"] = [{"id": 7, "deviceIds": [False]}]
    with pytest.raises(InvalidEvent):
        state.apply(snapshot)


async def test_reconstructed_exit_countdown_finishes_without_new_events(
    hass, snapshot, saved_credentials, freezer
):
    freezer.move_to("2026-10-09T10:00:00Z")
    snapshot["home"]["activeProfile"] = {
        "mode": "armed",
        "modeChangedAt": "2026-10-09T10:00:00Z",
    }
    snapshot["home"]["profiles"] = {"armed": {"exitDuration": 30}}

    async def stream(*args):
        yield snapshot
        await asyncio.Event().wait()

    entry = make_entry(hass)
    with patch("custom_components.eva.api.EvaClient.async_events", new=stream):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        alarm = entity_id(hass, "alarm_control_panel", "alarm")
        assert hass.states.get(alarm).state == "arming"
        freezer.tick(31)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
        assert hass.states.get(alarm).state == "armed_away"
        await hass.config_entries.async_unload(entry.entry_id)


async def test_initial_feature_flags_prevent_discovery_until_enabled(
    hass, snapshot, saved_credentials
):
    snapshot["home"]["rooms"][0]["devices"] = [device("lock", {"locked": True})]
    snapshot["home"]["moods"] = [{"id": "evening", "name": "Evening"}]
    queue = asyncio.Queue()

    async def stream(*args):
        yield {
            "eventType": "homeFeatures",
            "homeFeatures": {
                "doorLock": {"enabled": False},
                "moods": {"enabled": False},
            },
        }
        yield snapshot
        while True:
            yield await queue.get()

    entry = make_entry(hass)
    with patch("custom_components.eva.api.EvaClient.async_events", new=stream):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entity_id(hass, "lock", "lock:locked") is None
        assert entity_id(hass, "scene", "mood:evening") is None
        queue.put_nowait(
            {
                "eventType": "homeFeatures",
                "homeFeatures": {
                    "doorLock": {"enabled": True},
                    "moods": {"enabled": True},
                },
            }
        )
        await hass.async_block_till_done()
        assert hass.states.get(entity_id(hass, "lock", "lock:locked")).state == "locked"
        assert entity_id(hass, "scene", "mood:evening") is not None
        await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "event",
    [
        {"eventType": "deviceOffline", "deviceId": "lamp"},
        {"eventType": "deviceEnergySaverEnabled", "deviceId": "lamp"},
        {"eventType": "homeFeatures", "homeFeatures": {"groups": {"enabled": False}}},
    ],
)
async def test_groups_reject_unavailable_or_managed_members(hass, runtime, event):
    entry, queue, command, _ = runtime
    queue.put_nowait(event)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "eva",
            "set_group_attribute",
            {
                "config_entry_id": entry.entry_id,
                "group_id": 7,
                "attribute": "on",
                "value": False,
            },
            blocking=True,
        )
    command.assert_not_awaited()


@pytest.mark.parametrize(
    "error", [EvaAuthError("test auth failure"), EvaError("test network failure")]
)
async def test_read_actions_report_failure_and_reauth(hass, runtime, error):
    entry, _, _, read = runtime
    read.side_effect = error
    with patch.object(type(entry), "async_start_reauth") as reauth:
        with pytest.raises(HomeAssistantError, match=str(error)):
            await hass.services.async_call(
                "eva",
                "get_energy_saver",
                {"config_entry_id": entry.entry_id, "kind": "priority"},
                blocking=True,
                return_response=True,
            )
        assert reauth.call_count == (1 if isinstance(error, EvaAuthError) else 0)


async def test_group_command_completes_on_member_report(runtime):
    entry, _, command, _ = runtime
    coordinator = entry.runtime_data

    async def confirm(*args):
        for receive in tuple(coordinator._command_listeners):
            receive(
                {
                    "eventType": "deviceAttributeChanged",
                    "deviceId": "lamp",
                    "actionId": "group-action",
                    "name": "on",
                    "value": False,
                }
            )
        return "group-action"

    command.side_effect = confirm
    assert (
        await coordinator.async_command(
            "POST", ("groups", "7", "attributes", "on", "false")
        )
        is True
    )


async def test_energy_saver_commands_for_different_devices_do_not_supersede(runtime):
    entry, _, command, _ = runtime
    both_started = asyncio.Event()
    requests = 0

    async def save(*args):
        nonlocal requests
        requests += 1
        if requests == 2:
            both_started.set()
        await both_started.wait()
        return None

    command.side_effect = save
    results = await asyncio.gather(
        *(
            entry.runtime_data.async_command(
                "PATCH",
                ("energySaver", "devices", device_id, "settings"),
                {"enabled": True},
            )
            for device_id in ("first", "second")
        )
    )
    assert results == [True, True]


@pytest.mark.parametrize("hour", [-1, 24, 9.5, True])
def test_gateway_updates_reject_invalid_hours(hour):
    with pytest.raises(vol.Invalid):
        SCHEMAS["configure_gateway_updates"](
            {"config_entry_id": "test", "enabled": True, "hour_of_day": hour}
        )
