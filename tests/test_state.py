"""Snapshot replacement and partial-attribute merge regressions."""

from copy import deepcopy

import pytest

from custom_components.eva.state import HomeState, InvalidEvent


def test_partial_updates_preserve_absent_fields(snapshot):
    state = HomeState("test-home", {}, False).apply(snapshot)
    original = deepcopy(state)
    changed = state.apply(
        {
            "eventType": "deviceAttributeChanged",
            "deviceId": "test-device",
            "name": "temperature",
            "value": 0,
            "preview": None,
            "id": "test-event-2",
            "futureMetadata": False,
        }
    )
    attribute = changed.devices["test-device"]["attributes"]["temperature"]
    assert attribute == {
        "name": "temperature",
        "value": 0,
        "updatedAt": "2026-01-01T00:00:00Z",
        "minValue": -20,
        "maxValue": 60,
        "options": [20, 21.5],
        "preview": None,
        "futureMetadata": False,
    }
    assert state == original
    changed = changed.apply(
        {
            "eventType": "deviceAttributeChanged",
            "deviceId": "test-device",
            "name": "temperature",
            "value": None,
        }
    )
    assert changed.devices["test-device"]["attributes"]["temperature"]["value"] is None


def test_any_home_payload_replaces_state_and_removes_devices(snapshot):
    state = HomeState("test-home", {}, False).apply(snapshot)
    snapshot["eventType"] = "unknownFutureEvent"
    snapshot["home"]["rooms"][0]["devices"] = []
    assert state.apply(snapshot).devices == {}
    assert "test-device" in state.devices


def test_device_movement_and_rename_keep_identity(snapshot):
    state = HomeState("test-home", {}, False).apply(snapshot)
    snapshot["home"]["rooms"][0]["name"] = "Other room"
    snapshot["home"]["rooms"][0]["devices"][0]["name"] = "Renamed"
    moved = state.apply(snapshot)
    assert moved.devices.keys() == state.devices.keys()
    assert moved.devices["test-device"]["room_name"] == "Other room"


def test_offline_deleted_and_invalid_events(snapshot):
    state = HomeState("test-home", {}, False).apply(snapshot)
    offline = state.apply({"eventType": "deviceOffline", "deviceId": "test-device"})
    assert offline.devices["test-device"]["online"] is False
    assert state.apply({"eventType": "gatewayOffline"}).gateway_online is False
    assert (
        state.apply({"eventType": "deviceDeleted", "deviceId": "test-device"}).devices
        == {}
    )
    assert state.apply({"eventType": "keepAlive"}) is state
    with pytest.raises(InvalidEvent):
        state.apply({"eventType": "initialHome", "home": {"id": "other-home"}})
    with pytest.raises(InvalidEvent):
        state.apply(
            {
                "eventType": "deviceAttributeChanged",
                "deviceId": "unknown",
                "name": "temperature",
            }
        )


def test_live_moods_energy_saver_and_failed_pairing(snapshot):
    snapshot["home"]["moods"] = [{"id": "home-mood", "name": "Home", "active": True}]
    snapshot["home"]["rooms"][0]["moods"] = [{"id": "room-mood", "name": "Room"}]
    state = HomeState("test-home", {}, False).apply(snapshot)
    original = deepcopy(state)
    changed = state.apply(
        {"eventType": "activeMoodsChanged", "activeMoods": ["room-mood"]}
    )
    assert changed.moods["room-mood"]["active"] is True
    assert changed.moods["home-mood"]["active"] is False
    changed = changed.apply({"eventType": "moodActivated", "moodId": "home-mood"})
    assert changed.moods["home-mood"]["active"] is True
    assert changed.moods["room-mood"]["active"] is True
    changed = changed.apply({"eventType": "activeMoodsChanged", "activeMoods": []})
    assert not any(mood["active"] for mood in changed.moods.values())
    for event_type, enabled in [
        ("deviceEnergySaverEnabled", True),
        ("deviceEnergySaverDisabled", False),
    ]:
        changed = changed.apply({"eventType": event_type, "deviceId": "test-device"})
        assert changed.devices["test-device"]["energySaverEnabled"] is enabled
        assert (
            changed.devices["test-device"]["attributes"]
            == state.devices["test-device"]["attributes"]
        )
    assert (
        changed.apply(
            {"eventType": "deviceAddFailed", "deviceId": "test-device"}
        ).devices
        == {}
    )
    assert state == original
    for active in [None, "room-mood", [{}]]:
        with pytest.raises(InvalidEvent, match="active moods"):
            state.apply({"eventType": "activeMoodsChanged", "activeMoods": active})
