"""Door-lock state and lock/unlock commands."""

from homeassistant.components.lock import LockEntity, LockEntityDescription

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
    @property
    def is_locked(self):
        return self.boolean_value("locked")

    @property
    def is_jammed(self):
        return self.boolean_value("boltJammed")

    async def async_lock(self, **kwargs):
        await self.async_write("locked", True)

    async def async_unlock(self, **kwargs):
        await self.async_write("locked", False)
