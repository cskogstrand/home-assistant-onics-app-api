"""Apply the documented home snapshots and partial device attribute events."""

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any


class InvalidEvent(ValueError):
    """An event cannot safely be applied to the current home."""


@dataclass(frozen=True)
class HomeState:
    """Only the home state needed by the sensor platform; no user or address data."""

    home_id: str
    devices: dict[str, dict[str, Any]]
    gateway_online: bool

    def apply(self, event: dict[str, Any]) -> HomeState:
        """Replace complete snapshots; merge only supplied attribute fields."""
        if "home" in event:
            home = event["home"]
            if not isinstance(home, dict) or home.get("id") != self.home_id:
                raise InvalidEvent("Snapshot does not match the selected home")
            rooms = home.get("rooms")
            gateway = home.get("gateway")
            if not isinstance(rooms, list) or not isinstance(gateway, dict):
                raise InvalidEvent("Invalid home snapshot")
            devices = {}
            for room in rooms:
                if not isinstance(room, dict) or not isinstance(
                    room.get("devices"), list
                ):
                    raise InvalidEvent("Invalid room in snapshot")
                for device in room["devices"]:
                    if not isinstance(device, dict) or not isinstance(
                        device.get("id"), str
                    ):
                        raise InvalidEvent("Invalid device in snapshot")
                    attributes = device.get("attributes")
                    if not isinstance(attributes, list) or any(
                        not isinstance(attribute, dict)
                        or not isinstance(attribute.get("name"), str)
                        for attribute in attributes
                    ):
                        raise InvalidEvent("Invalid device attributes")
                    devices[device["id"]] = {
                        **deepcopy(device),
                        "attributes": {
                            attribute["name"]: deepcopy(attribute)
                            for attribute in attributes
                        },
                        "room_name": room.get("name"),
                    }
            return HomeState(self.home_id, devices, gateway.get("online") is True)

        event_type = event.get("eventType")
        if event_type == "homeDeleted":
            return HomeState(self.home_id, {}, False)
        if event_type in {"gatewayOnline", "gatewayOffline"}:
            return replace(self, gateway_online=event_type == "gatewayOnline")
        device_id = event.get("deviceId")
        if not isinstance(device_id, str):
            return self
        if event_type == "deviceDeleted":
            return replace(
                self, devices={k: v for k, v in self.devices.items() if k != device_id}
            )
        if event_type not in {
            "deviceAttributeChanged",
            "deviceAttributeReport",
            "deviceOnline",
            "deviceOffline",
        }:
            return self
        if device_id not in self.devices:
            # An incomplete replay must be followed by a fresh snapshot.
            raise InvalidEvent("Event references an unknown device")
        device = self.devices[device_id]
        if event_type in {"deviceOnline", "deviceOffline"}:
            device = {**device, "online": event_type == "deviceOnline"}
        else:
            name = event.get("name")
            if not isinstance(name, str):
                raise InvalidEvent("Attribute event has no name")
            # Exclude event-envelope fields; retain all supplied attribute fields,
            # including future attribute metadata, explicit nulls and false values.
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
