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
                        key="ping"
                        if device.get("resource") == "gateway"
                        else "identify",
                        translation_key="ping"
                        if device.get("resource") == "gateway"
                        else "identify",
                        device_class=ButtonDeviceClass.IDENTIFY,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                )
            ]
            if device.get("supportsIdentify") is True
            or device.get("resource") == "gateway"
            else []
        ),
    )


class EvaButton(EvaEntity, ButtonEntity):
    @property
    def available(self):
        return super().available and (
            self.device.get("supportsIdentify") is True
            or self.device.get("resource") == "gateway"
        )

    async def async_press(self):
        if self.device.get("resource") == "gateway":
            await self.coordinator.async_command(
                "POST", ("gateway", "ping"), requires_gateway=False
            )
            return
        await self.coordinator.async_command(
            "POST", ("devices", self._device_id, "identify")
        )
