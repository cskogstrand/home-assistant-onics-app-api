"""Shared discovery, identity, availability and validated commands."""

import json
import re
from collections.abc import Callable, Iterable
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .capabilities import number, validate_value
from .const import DOMAIN
from .coordinator import EvaConfigEntry, EvaCoordinator


def translation_key(key: str) -> str:
    """Use one stable translation key for camel-case API attributes."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()


def device_data(coordinator: EvaCoordinator, device_id: str) -> dict:
    """External charger fields come from their documented status endpoint."""
    device = coordinator.data.devices.get(device_id, {})
    if device.get("external") is True and device.get("type") == "evCharger":
        status = coordinator.external_status.get(device_id) or {}
        return {
            **device,
            "attributes": {
                **device.get("attributes", {}),
                **{
                    key: {"name": key, "value": status.get(key)}
                    for key in ("charging", "carPluggedIn", "currentPower")
                },
            },
        }
    return device


@callback
def async_discover(
    entry: EvaConfigEntry,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[EvaCoordinator, str, dict], Iterable[EvaEntity]],
) -> None:
    """Share live discovery and deletion handling across every device platform."""
    coordinator = entry.runtime_data
    known: dict[str, str] = {}

    @callback
    def discover() -> None:
        for unique_id, device_id in tuple(known.items()):
            if device_id not in coordinator.data.devices:
                del known[unique_id]
        entities = []
        for device_id in coordinator.data.devices:
            device = device_data(coordinator, device_id)
            for entity in factory(coordinator, device_id, device):
                if entity.unique_id not in known:
                    known[entity.unique_id] = device_id
                    entities.append(entity)
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class EvaEntity(CoordinatorEntity[EvaCoordinator]):
    """Stable identity and current data, never optimistic device state."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EvaCoordinator,
        device_id: str,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}:{device_id}:{description.key}"
        )

    @property
    def device(self) -> dict:
        return device_data(self.coordinator, self._device_id)

    @property
    def attributes(self) -> dict:
        return self.device.get("attributes", {})

    def attribute_value(self, key: str) -> Any:
        return self.attributes.get(key, {}).get("value")

    def numeric_value(self, key: str) -> float | None:
        return number(self.attribute_value(key))

    def boolean_value(self, key: str) -> bool | None:
        value = self.attribute_value(key)
        return value if type(value) is bool else None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self.coordinator.config_entry.unique_id}:{self._device_id}")
            },
            name=self.device.get("name"),
            manufacturer=self.device.get("vendor"),
            model=self.device.get("model"),
            sw_version=self.device.get("softwareVersion"),
            hw_version=self.device.get("hardwareVersion"),
            suggested_area=self.device.get("room_name"),
        )

    @property
    def available(self) -> bool:
        if (
            self.device.get("external") is True
            and self.device.get("type") == "evCharger"
        ):
            return (
                super().available
                and self.coordinator.external_status.get(self._device_id) is not None
                and not self.device.get("externalReconnectRequired", False)
            )
        return (
            super().available
            and self.coordinator.data.gateway_online
            and self.device.get("online") is True
        )

    async def async_write(self, key: str, value: Any) -> bool:
        """Validate and confirm a write; return False if a newer command replaces it."""
        self.check_control_available()
        try:
            value = validate_value(self.device, key, value)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err
        encoded = (
            value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        )
        resource = self.device.get("resource", "devices")
        return await self.coordinator.async_command(
            "POST" if resource == "groups" else "PATCH",
            (
                resource,
                str(self.device.get("id", self._device_id)),
                "attributes",
                key,
                encoded,
            ),
        )

    def check_control_available(self) -> None:
        """Reject unavailable and automatically managed devices for every control."""
        if not self.available:
            raise HomeAssistantError("Eva device is unavailable")
        if self.device.get("energySaverEnabled") is True:
            raise ServiceValidationError(
                "Manual control is disabled while Eva Energy Saver manages this device"
            )

    def validate_writes(self, writes: list[tuple[str, Any]]) -> None:
        """Validate every part of a compound command before sending its first write."""
        try:
            for key, value in writes:
                validate_value(self.device, key, value)
        except ValueError as err:
            raise ServiceValidationError(str(err)) from err


class EvaAttributeEntity(EvaEntity):
    """An entity that becomes unavailable if its capability disappears."""

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.key in self.attributes
