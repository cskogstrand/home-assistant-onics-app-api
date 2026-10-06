"""Thermostat display and physical mood button assignments."""

from homeassistant.components.text import TextEntity, TextEntityDescription
from homeassistant.const import EntityCategory

from .capabilities import ATTRIBUTES, platform_for
from .entity import EvaAttributeEntity, async_discover, translation_key

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            EvaText(
                coordinator,
                device_id,
                TextEntityDescription(
                    key=key,
                    translation_key=translation_key(key),
                    entity_category=EntityCategory.CONFIG,
                    native_min=0,
                    native_max=int(ATTRIBUTES[key].maximum or 255),
                ),
            )
            for key in device["attributes"]
            if platform_for(device, key) == "text"
        ),
    )


class EvaText(EvaAttributeEntity, TextEntity):
    @property
    def native_value(self):
        value = self.attribute_value(self.entity_description.key)
        return value if isinstance(value, str) else None

    async def async_set_value(self, value):
        await self.async_write(self.entity_description.key, value)
