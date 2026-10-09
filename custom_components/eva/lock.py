"""Door-lock state and lock/unlock commands."""

from homeassistant.components.lock import LockEntity, LockEntityDescription
from homeassistant.const import ATTR_CODE
from homeassistant.exceptions import ServiceValidationError

from .entity import EvaAttributeEntity, async_discover

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            [
                EvaLock(
                    coordinator,
                    device_id,
                    LockEntityDescription(key="locked", name=None),
                )
            ]
            if "locked" in device["attributes"]
            else []
        ),
    )


class EvaLock(EvaAttributeEntity, LockEntity):
    _attr_code_format = "^[0-9]*$"

    @property
    def is_locked(self):
        return self.boolean_value("locked")

    @property
    def is_jammed(self):
        return self.boolean_value("boltJammed")

    async def async_lock(self, **kwargs):
        await self.async_write("locked", True)

    async def async_unlock(self, **kwargs):
        code = kwargs.get(ATTR_CODE)
        if code is None or code == "":
            await self.async_write("locked", False)
            return
        if not isinstance(code, str) or not code.isascii() or not code.isdecimal():
            raise ServiceValidationError("The lock PIN must contain only digits")
        self.check_control_available()
        self.validate_writes([("locked", False)])
        await self.coordinator.async_command(
            "PATCH",
            ("devices", self._device_id),
            {"attributes": [{"name": "locked", "value": False, "authPin": code}]},
        )
