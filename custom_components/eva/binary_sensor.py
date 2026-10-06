"""Safety, occupancy, contact and diagnostic attributes."""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)

from .capabilities import ATTRIBUTES, platform_for
from .entity import EvaAttributeEntity, async_discover, translation_key

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            EvaBinarySensor(
                coordinator,
                device_id,
                BinarySensorEntityDescription(
                    key=key,
                    translation_key=translation_key(key),
                    device_class=ATTRIBUTES[key].device_class,
                ),
            )
            for key in device["attributes"]
            if platform_for(device, key) == "binary_sensor"
        ),
    )


class EvaBinarySensor(EvaAttributeEntity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.boolean_value(self.entity_description.key)
