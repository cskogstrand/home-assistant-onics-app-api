"""Numeric settings with documented or device-supplied bounds."""

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import EntityCategory

from .capabilities import ATTRIBUTES, limits, platform_for
from .entity import EvaAttributeEntity, async_discover, translation_key

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            EvaNumber(
                coordinator,
                device_id,
                NumberEntityDescription(
                    key=key,
                    translation_key=translation_key(key),
                    native_unit_of_measurement=ATTRIBUTES[key].unit,
                    entity_category=EntityCategory.CONFIG,
                ),
            )
            for key in device["attributes"]
            if platform_for(device, key) == "number"
        ),
    )


class EvaNumber(EvaAttributeEntity, NumberEntity):
    @property
    def available(self):
        return (
            super().available
            and platform_for(self.device, self.entity_description.key) == "number"
        )

    @property
    def native_value(self):
        return self.numeric_value(self.entity_description.key)

    @property
    def native_min_value(self):
        if self.entity_description.key not in self.attributes:
            return 0
        return limits(self.device, self.entity_description.key)[0] or 0

    @property
    def native_max_value(self):
        if self.entity_description.key not in self.attributes:
            return 0
        return limits(self.device, self.entity_description.key)[1] or 0

    @property
    def native_step(self):
        if self.entity_description.key not in self.attributes:
            return 1
        return limits(self.device, self.entity_description.key)[2]

    async def async_set_native_value(self, value):
        await self.async_write(self.entity_description.key, value)
