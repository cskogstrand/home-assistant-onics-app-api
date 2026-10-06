"""Enumerated settings use the API's supported options."""

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory

from .capabilities import options, platform_for
from .entity import EvaAttributeEntity, async_discover, translation_key

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            EvaSelect(
                coordinator,
                device_id,
                SelectEntityDescription(
                    key=key,
                    translation_key=translation_key(key),
                    entity_category=EntityCategory.CONFIG,
                ),
            )
            for key in device["attributes"]
            if platform_for(device, key) == "select"
        ),
    )


class EvaSelect(EvaAttributeEntity, SelectEntity):
    @property
    def available(self):
        return super().available and bool(self.options)

    @property
    def options(self):
        if self.entity_description.key not in self.attributes:
            return []
        return options(self.device, self.entity_description.key)

    @property
    def current_option(self):
        value = self.attribute_value(self.entity_description.key)
        return value if value in self.options else None

    async def async_select_option(self, option):
        await self.async_write(self.entity_description.key, option)
