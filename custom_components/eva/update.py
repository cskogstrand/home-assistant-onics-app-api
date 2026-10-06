"""Firmware updates advertised by Eva; no fabricated available versions."""

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.const import EntityCategory
from homeassistant.exceptions import ServiceValidationError

from .capabilities import number
from .entity import EvaEntity, async_discover

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            [
                EvaUpdate(
                    coordinator,
                    device_id,
                    UpdateEntityDescription(
                        key="firmware",
                        translation_key="firmware",
                        device_class=UpdateDeviceClass.FIRMWARE,
                        entity_category=EntityCategory.CONFIG,
                    ),
                )
            ]
            if "softwareUpdate" in device
            else []
        ),
    )


class EvaUpdate(EvaEntity, UpdateEntity):
    _attr_supported_features = (
        UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
    )

    @property
    def installed_version(self):
        return self.device.get("softwareVersion")

    @property
    def latest_version(self):
        return (self.device.get("softwareUpdate") or {}).get(
            "version", self.installed_version
        )

    @property
    def in_progress(self):
        return (self.device.get("softwareUpdate") or {}).get("status") in {
            "assigned",
            "inProgress",
        }

    @property
    def update_percentage(self):
        value = number((self.device.get("softwareUpdate") or {}).get("progress"))
        return value if value is not None and 0 <= value <= 100 else None

    async def async_install(self, version, backup, **kwargs):
        if (
            version is not None
            or backup
            or (self.device.get("softwareUpdate") or {}).get("status") != "available"
        ):
            raise ServiceValidationError(
                "Only the available Eva firmware can be installed"
            )
        await self.coordinator.async_command(
            "POST", ("devices", self._device_id, "updateSoftware")
        )
