"""On/off devices and boolean configuration capabilities."""

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory

from .capabilities import platform_for
from .entity import EvaAttributeEntity, async_discover, translation_key

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            EvaSwitch(
                coordinator,
                device_id,
                SwitchEntityDescription(
                    key=key,
                    translation_key=translation_key(key)
                    if key not in {"on", "charging"}
                    else None,
                    name=None,
                    entity_category=EntityCategory.CONFIG
                    if key not in {"on", "charging"}
                    else None,
                ),
            )
            for key in device["attributes"]
            if platform_for(device, key) == "switch"
        ),
    )


class EvaSwitch(EvaAttributeEntity, SwitchEntity):
    @property
    def is_on(self):
        return self.boolean_value(self.entity_description.key)

    async def async_turn_on(self, **kwargs):
        await self._async_set(True)

    async def async_turn_off(self, **kwargs):
        await self._async_set(False)

    async def _async_set(self, value):
        if self.entity_description.key == "charging":
            self.validate_writes([("charging", value)])
            self.check_control_available()
            await self.coordinator.async_command(
                "POST",
                (
                    "devices",
                    self._device_id,
                    "external",
                    "evCharger",
                    "start" if value else "stop",
                ),
            )
            return
        await self.async_write(self.entity_description.key, value)
