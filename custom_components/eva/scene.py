"""Activate existing Eva home and room moods as Home Assistant scenes."""

from homeassistant.components.scene import Scene
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    known = set()

    @callback
    def discover():
        moods = coordinator.data.moods
        registry = er.async_get(hass)
        unique_ids = {f"{entry.unique_id}:mood:{mood_id}" for mood_id in moods}
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
            if entity.domain == "scene" and entity.unique_id not in unique_ids:
                registry.async_remove(entity.entity_id)
        known.intersection_update(moods)
        async_add_entities(
            [
                EvaScene(coordinator, mood_id)
                for mood_id in moods
                if mood_id not in known and coordinator.data.feature_enabled("moods")
            ]
        )
        if coordinator.data.feature_enabled("moods"):
            known.update(moods)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class EvaScene(CoordinatorEntity, Scene):
    _attr_has_entity_name = True

    def __init__(self, coordinator, mood_id):
        super().__init__(coordinator)
        self._mood_id = mood_id
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}:mood:{mood_id}"

    @property
    def name(self):
        return self.coordinator.data.moods.get(self._mood_id, {}).get("name")

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.data.feature_enabled("moods")
            and self.coordinator.data.gateway_online
            and self._mood_id in self.coordinator.data.moods
        )

    @property
    def extra_state_attributes(self):
        return {
            "active": self.coordinator.data.moods.get(self._mood_id, {}).get("active")
        }

    async def async_activate(self, **kwargs):
        await self.coordinator.async_command(
            "POST", ("moods", self._mood_id, "activate")
        )
