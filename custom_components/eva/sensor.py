"""Measurements and read-only fallbacks for every Eva attribute."""

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory

from .capabilities import ATTRIBUTES, Attribute, number, platform_for
from .entity import EvaAttributeEntity, async_discover, translation_key

PARALLEL_UPDATES = 0


def description(key):
    """Keep existing temperature identities while adding measured capabilities."""
    spec = ATTRIBUTES.get(key, Attribute(kind=object))
    state_class = None
    if spec.platform == "sensor" and spec.kind in (int, float):
        state_class = SensorStateClass.MEASUREMENT
        if key in {"electricityConsumptionSummary", "waterConsumptionSummary"}:
            state_class = SensorStateClass.TOTAL_INCREASING
        elif key.startswith("electricityConsumptionCurrentHour"):
            state_class = (
                None  # Rolling hourly values are not cumulative meter readings.
            )
    return SensorEntityDescription(
        key=key,
        translation_key=translation_key(key) if key in ATTRIBUTES else None,
        name=None if key in ATTRIBUTES else key,
        native_unit_of_measurement=spec.unit,
        device_class=spec.device_class if spec.platform == "sensor" else None,
        state_class=state_class,
        entity_category=EntityCategory.DIAGNOSTIC if spec.diagnostic else None,
    )


DESCRIPTIONS = tuple(
    description(key) for key in ("temperature", "airTemperature", "floorTemperature")
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            EvaSensor(coordinator, device_id, description(key))
            for key in device["attributes"]
            if platform_for(device, key) == "sensor"
        ),
    )


class EvaSensor(EvaAttributeEntity, SensorEntity):
    """Use real measurements and retain unknown scalar attributes without controls."""

    @property
    def available(self):
        return (
            super().available
            and platform_for(self.device, self.entity_description.key) == "sensor"
        )

    @property
    def native_value(self):
        key = self.entity_description.key
        value = self.attribute_value(key)
        spec = ATTRIBUTES.get(key)
        if spec is not None:
            if spec.kind in (float, int):
                return number(value)
            if spec.kind is str:
                return value[:255] if isinstance(value, str) else None
        if type(value) is bool:
            return str(value).lower()
        if isinstance(value, str):
            return value[:255]
        return number(value)

    @property
    def native_unit_of_measurement(self):
        unit = self.attributes.get(self.entity_description.key, {}).get("unit")
        return self.entity_description.native_unit_of_measurement or (
            unit if isinstance(unit, str) else None
        )
