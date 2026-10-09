"""Apply authoritative snapshots and partial SSE updates without retaining users."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any


class InvalidEvent(ValueError):
    """An event cannot safely be applied to the current home."""


@dataclass(frozen=True)
class HomeState:
    """Only entity state and metadata; no user, address or PIN data."""

    home_id: str
    devices: dict[str, dict[str, Any]]
    gateway_online: bool
    moods: dict[str, dict[str, Any]] = field(default_factory=dict)
    alarm: dict[str, Any] = field(default_factory=dict)
    features: dict[str, bool] = field(default_factory=dict)
    groups: dict[int, dict] = field(default_factory=dict)

    def feature_enabled(self, name: str) -> bool:
        """Use server flags; older streams without flags retain capability discovery."""
        return self.features.get(name, True)

    def device_enabled(self, device: dict) -> bool:
        """Require each advertised home feature used by this device."""
        attributes = device.get("attributes", {})
        return all(
            self.feature_enabled(name)
            for name, applies in {
                "groups": device.get("resource") == "groups",
                "externalDevices": device.get("external") is True,
                "evCharger": device.get("type") in ("evCharger", "evChargingStation"),
                "thermostats": "setpoint" in attributes,
                "doorLock": "locked" in attributes,
                "cameras": device.get("type") == "CAMERA",
            }.items()
            if applies
        )

    def apply(self, event: dict[str, Any]) -> HomeState:
        """Replace snapshots; merge only the fields actually supplied in events."""
        if event.get("eventType") == "homeFeatures":
            features = event.get("homeFeatures")
            if not isinstance(features, dict) or any(
                not isinstance(value, dict) or type(value.get("enabled")) is not bool
                for value in features.values()
            ):
                raise InvalidEvent("Invalid home features")
            return replace(
                self,
                features={key: value["enabled"] for key, value in features.items()},
            )
        if "home" in event:
            home = event["home"]
            if not isinstance(home, dict) or home.get("id") != self.home_id:
                raise InvalidEvent("Snapshot does not match the selected home")
            rooms, gateway = home.get("rooms"), home.get("gateway")
            if not isinstance(rooms, list) or not isinstance(gateway, dict):
                raise InvalidEvent("Invalid home snapshot")
            devices, moods = {}, {}
            for container in [home, *rooms]:
                if not isinstance(container, dict):
                    raise InvalidEvent("Invalid room in snapshot")
                entries = container.get("moods", [])
                if not isinstance(entries, list):
                    raise InvalidEvent("Invalid moods")
                for mood in entries:
                    if not isinstance(mood, dict) or not isinstance(
                        mood.get("id"), str
                    ):
                        raise InvalidEvent("Invalid mood")
                    moods[mood["id"]] = {
                        "name": mood.get("name", mood["id"]),
                        "active": mood.get("active") is True,
                    }
            for room in rooms:
                for resource in ("devices", "groups"):
                    entries = room.get(resource, [] if resource == "groups" else None)
                    if not isinstance(entries, list):
                        raise InvalidEvent("Invalid room devices or groups")
                    for device in entries:
                        if not isinstance(device, dict) or type(
                            device.get("id")
                        ) is not (int if resource == "groups" else str):
                            raise InvalidEvent("Invalid device in snapshot")
                        attributes = device.get(
                            "attributes", [] if device.get("external") is True else None
                        )
                        if not isinstance(attributes, list) or any(
                            not isinstance(attribute, dict)
                            or not isinstance(attribute.get("name"), str)
                            for attribute in attributes
                        ):
                            raise InvalidEvent("Invalid device attributes")
                        device_id = (
                            f"group:{device['id']}"
                            if resource == "groups"
                            else device["id"]
                        )
                        devices[device_id] = {
                            **deepcopy(device),
                            "resource": resource,
                            "attributes": {
                                attribute["name"]: deepcopy(attribute)
                                for attribute in attributes
                            },
                            "room_name": room.get("name"),
                        }
            groups = home.get("groups", [])
            if not isinstance(groups, list) or any(
                not isinstance(group, dict)
                or type(group.get("id")) is not int
                or not isinstance(group.get("deviceIds"), list)
                or any(not isinstance(member, str) for member in group["deviceIds"])
                for group in groups
            ):
                raise InvalidEvent("Invalid top-level groups")
            if isinstance(gateway.get("id"), str) and gateway["id"]:
                devices[f"gateway:{gateway['id']}"] = {
                    **deepcopy(gateway),
                    "resource": "gateway",
                    "attributes": {},
                }
            profile = home.get("activeProfile")
            settings = home.get("settings") or {}
            if not isinstance(settings, dict) or not isinstance(
                settings.get("alarm", {}), dict
            ):
                raise InvalidEvent("Invalid alarm settings")
            alarm = {}
            if isinstance(profile, dict):
                mode = profile.get("mode")
                changed_at = profile.get("modeChangedAt")
                same_profile = mode == self.alarm.get("mode") and (
                    changed_at is None
                    or self.alarm.get("mode_changed_at") is None
                    or changed_at == self.alarm["mode_changed_at"]
                )
                alarm = {
                    "mode": mode,
                    "mode_changed_at": changed_at,
                    "pin_required": settings.get("alarm", {}).get("pinRequired")
                    is True,
                }
                if mode in ("armed", "dayArmed", "nightArmed"):
                    if same_profile:
                        alarm.update(
                            {
                                key: self.alarm[key]
                                for key in ("entry_at", "exit_at")
                                if key in self.alarm
                            }
                        )
                    profiles = home.get("profiles", {})
                    durations = (
                        profiles.get(mode, {}) if isinstance(profiles, dict) else {}
                    )
                    duration = (
                        durations.get("exitDuration", 30)
                        if isinstance(durations, dict)
                        else None
                    )
                    if (
                        "exit_at" not in alarm
                        and isinstance(changed_at, str)
                        and type(duration) is int
                        and 0 <= duration <= 120
                    ):
                        try:
                            changed = datetime.fromisoformat(changed_at)
                            if changed.tzinfo is not None:
                                alarm["exit_at"] = (
                                    changed + timedelta(seconds=duration)
                                ).isoformat()
                        except ValueError, OverflowError:
                            pass
            return HomeState(
                self.home_id,
                devices,
                gateway.get("online") is True,
                moods,
                alarm,
                self.features,
                {group["id"]: deepcopy(group) for group in groups},
            )

        event_type = event.get("eventType")
        if event_type == "homeDeleted":
            return HomeState(self.home_id, {}, False)
        if event_type in {"gatewayOnline", "gatewayOffline"}:
            return replace(self, gateway_online=event_type == "gatewayOnline")
        if event_type in {
            "gatewaySoftwareUpdateAvailable",
            "gatewaySoftwareUpdateAssigned",
            "gatewaySoftwareUpdateInProgress",
            "gatewayAutomaticSoftwareUpdatesSaved",
        }:
            key = (
                "automaticSoftwareUpdates"
                if event_type == "gatewayAutomaticSoftwareUpdatesSaved"
                else "softwareUpdate"
            )
            value = event.get(key)
            if not isinstance(value, dict):
                return self
            return replace(
                self,
                devices={
                    device_id: {**device, key: deepcopy(value)}
                    if device.get("resource") == "gateway"
                    else device
                    for device_id, device in self.devices.items()
                },
            )
        if event_type == "activeMoodsChanged":
            active = event.get("activeMoods")
            if not isinstance(active, list) or any(
                not isinstance(mood_id, str) for mood_id in active
            ):
                raise InvalidEvent("Invalid active moods")
            return replace(
                self,
                moods={
                    mood_id: {**mood, "active": mood_id in active}
                    for mood_id, mood in self.moods.items()
                },
            )
        if event_type == "moodActivated":
            mood_id = event.get("moodId")
            if isinstance(mood_id, str) and mood_id in self.moods:
                return replace(
                    self,
                    moods={
                        **self.moods,
                        mood_id: {**self.moods[mood_id], "active": True},
                    },
                )
            return self
        if event_type in {"activeProfileUpdated", "activeProfileExitTimeExpired"}:
            profile = event.get("activeProfile")
            if not isinstance(profile, dict):
                raise InvalidEvent("Invalid alarm profile")
            return replace(
                self,
                alarm={
                    "mode": profile.get("mode"),
                    "mode_changed_at": profile.get("modeChangedAt"),
                    "pin_required": self.alarm.get("pin_required", False),
                    "exit_at": event.get("estimatedExitDelayExpiresAt"),
                },
            )
        if event_type == "activeProfileEntryTimeStarted":
            return replace(
                self,
                alarm={
                    **self.alarm,
                    "entry_at": event.get("estimatedEntryDelayExpiresAt"),
                },
            )
        device_id = event.get("deviceId")
        if event_type in {
            "groupAttributeChanged",
            "groupAttributeReport",
            "groupOnline",
            "groupOffline",
            "groupDeleted",
        }:
            if type(event.get("groupId")) is int and event["groupId"] in self.groups:
                if event_type == "groupDeleted":
                    return replace(
                        self,
                        groups={
                            key: group
                            for key, group in self.groups.items()
                            if key != event["groupId"]
                        },
                    )
                # Top-level groups report their members' states, not an aggregate.
                return self
            device_id = f"group:{event.get('groupId')}"
            event_type = event_type.replace("group", "device", 1)
        if not isinstance(device_id, str):
            return self
        if event_type in {"deviceDeleted", "deviceAddFailed"}:
            return replace(
                self, devices={k: v for k, v in self.devices.items() if k != device_id}
            )
        if event_type in {
            "deviceSoftwareUpdateAssigned",
            "deviceSoftwareUpdateInProgress",
            "deviceSoftwareUpdateFailed",
        }:
            if device_id not in self.devices or not isinstance(
                event.get("softwareUpdate"), dict
            ):
                raise InvalidEvent("Invalid device firmware update")
            device = self.devices[device_id]
            return replace(
                self,
                devices={
                    **self.devices,
                    device_id: {
                        **device,
                        "softwareUpdate": {
                            **(device.get("softwareUpdate") or {}),
                            **deepcopy(event["softwareUpdate"]),
                        },
                    },
                },
            )
        if event_type not in {
            "deviceAttributeChanged",
            "deviceAttributeReport",
            "deviceOnline",
            "deviceOffline",
            "deviceEnergySaverEnabled",
            "deviceEnergySaverDisabled",
        }:
            return self
        if device_id not in self.devices:
            raise InvalidEvent("Event references an unknown device")
        device = self.devices[device_id]
        if event_type in {"deviceOnline", "deviceOffline"}:
            device = {**device, "online": event_type == "deviceOnline"}
        elif event_type in {"deviceEnergySaverEnabled", "deviceEnergySaverDisabled"}:
            device = {
                **device,
                "energySaverEnabled": event_type == "deviceEnergySaverEnabled",
            }
        else:
            name = event.get("name")
            if not isinstance(name, str):
                raise InvalidEvent("Attribute event has no name")
            fields = {
                key: value
                for key, value in event.items()
                if key
                not in {
                    "eventType",
                    "deviceId",
                    "deviceName",
                    "actionId",
                    "timestamp",
                    "id",
                    "userEmail",
                    "homeId",
                    "groupIds",
                    "groupId",
                }
            }
            attributes = device["attributes"]
            device = {
                **device,
                "attributes": {
                    **attributes,
                    name: {**attributes.get(name, {}), **deepcopy(fields)},
                },
            }
        return replace(self, devices={**self.devices, device_id: device})
