"""Identify devices that explicitly advertise the capability."""

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.const import EntityCategory

from .entity import EvaEntity, async_discover

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            [
                EvaButton(
                    coordinator,
                    device_id,
                    ButtonEntityDescription(
                        key="identify",
                        translation_key="identify",
                        device_class=ButtonDeviceClass.IDENTIFY,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                )
            ]
            if device.get("supportsIdentify") is True
            else []
        ),
    )


class EvaButton(EvaEntity, ButtonEntity):
    @property
    def available(self):
        return super().available and self.device.get("supportsIdentify") is True

    async def async_press(self):
        await self.coordinator.async_command(
            "POST", ("devices", self._device_id, "identify")
        )
