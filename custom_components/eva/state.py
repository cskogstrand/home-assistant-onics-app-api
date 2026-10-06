"""Apply authoritative snapshots and partial SSE updates without retaining users."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
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

    def apply(self, event: dict[str, Any]) -> HomeState:
        """Replace snapshots; merge only the fields actually supplied in events."""
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
            profile = home.get("activeProfile")
            settings = home.get("settings") or {}
            if not isinstance(settings, dict) or not isinstance(
                settings.get("alarm", {}), dict
            ):
                raise InvalidEvent("Invalid alarm settings")
            alarm = {}
            if isinstance(profile, dict):
                alarm = {
                    "mode": profile.get("mode"),
                    "pin_required": settings.get("alarm", {}).get("pinRequired")
                    is True,
                }
            return HomeState(
                self.home_id, devices, gateway.get("online") is True, moods, alarm
            )

        event_type = event.get("eventType")
        if event_type == "homeDeleted":
            return HomeState(self.home_id, {}, False)
        if event_type in {"gatewayOnline", "gatewayOffline"}:
            return replace(self, gateway_online=event_type == "gatewayOnline")
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
