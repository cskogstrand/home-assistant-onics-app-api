"""Read-only temperature sensors backed exclusively by Onics state."""

import math

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import OnicsConfigEntry, OnicsCoordinator

DESCRIPTIONS = tuple(
    SensorEntityDescription(
        key=key,
        translation_key=translation_key,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    )
    for key, translation_key in (
        ("temperature", "temperature"),
        ("airTemperature", "air_temperature"),
        ("floorTemperature", "floor_temperature"),
    )
)
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnicsConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add discovered attributes, including those introduced by later snapshots."""
    coordinator = entry.runtime_data
    known: set[tuple[str, str]] = set()

    @callback
    def add_sensors() -> None:
        entities = []
        for device_id, device in coordinator.data.devices.items():
            for description in DESCRIPTIONS:
                key = (device_id, description.key)
                if description.key in device["attributes"] and key not in known:
                    known.add(key)
                    entities.append(
                        OnicsTemperatureSensor(coordinator, device_id, description)
                    )
        async_add_entities(entities)

    add_sensors()
    entry.async_on_unload(coordinator.async_add_listener(add_sensors))


class OnicsTemperatureSensor(CoordinatorEntity[OnicsCoordinator], SensorEntity):
    """A stable environment/home/device/attribute identity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: OnicsCoordinator,
        device_id: str,
        description: SensorEntityDescription,
    ) -> None:
        """Describe a measured attribute present in an actual device snapshot."""
        super().__init__(coordinator)
        self._device_id = device_id
        self.entity_description = description
        self._attr_unique_id = (
            f"{coordinator.config_entry.unique_id}:{device_id}:{description.key}"
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Use API device identity and metadata, never the account's credentials."""
        device = self.coordinator.data.devices.get(self._device_id, {})
        return DeviceInfo(
            identifiers={
                (DOMAIN, f"{self.coordinator.config_entry.unique_id}:{self._device_id}")
            },
            name=device.get("name"),
            manufacturer=device.get("vendor"),
            model=device.get("model"),
            sw_version=device.get("softwareVersion"),
            suggested_area=device.get("room_name"),
        )

    @property
    def available(self) -> bool:
        """Disconnects, offline devices, and removed attributes are unavailable."""
        state = self.coordinator.data
        device = state.devices.get(self._device_id, {})
        return (
            super().available
            and state.gateway_online
            and device.get("online") is True
            and self.entity_description.key in device.get("attributes", {})
        )

    @property
    def native_value(self) -> float | None:
        """Null and invalid readings stay unknown; never fabricate measurements."""
        device = self.coordinator.data.devices.get(self._device_id, {})
        value = (
            device.get("attributes", {})
            .get(self.entity_description.key, {})
            .get("value")
        )
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            return value
        return None
