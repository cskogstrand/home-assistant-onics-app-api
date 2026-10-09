"""Expose the home's documented burglary alarm profiles and countdowns."""

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

PARALLEL_UPDATES = 0
MODES = {
    "disarmed": AlarmControlPanelState.DISARMED,
    "armed": AlarmControlPanelState.ARMED_AWAY,
    "dayArmed": AlarmControlPanelState.ARMED_HOME,
    "nightArmed": AlarmControlPanelState.ARMED_NIGHT,
}


async def async_setup_entry(hass, entry, async_add_entities):
    added = False

    @callback
    def discover():
        nonlocal added
        if entry.runtime_data.data.alarm and not added:
            added = True
            async_add_entities([EvaAlarm(entry.runtime_data)])

    discover()
    entry.async_on_unload(entry.runtime_data.async_add_listener(discover))


class EvaAlarm(CoordinatorEntity, AlarmControlPanelEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "alarm"
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.unique_id}:alarm"
        self._cancel_countdown = None

    @property
    def available(self):
        return (
            super().available
            and self.coordinator.data.gateway_online
            and bool(self.coordinator.data.alarm)
        )

    @property
    def code_arm_required(self):
        return self.coordinator.data.alarm.get("pin_required", False)

    @property
    def code_format(self):
        return CodeFormat.NUMBER if self.code_arm_required else None

    @property
    def alarm_state(self):
        alarm = self.coordinator.data.alarm
        if alarm.get("entry_at"):
            return AlarmControlPanelState.PENDING
        expires = self._exit_time()
        if expires and dt_util.as_utc(expires) > dt_util.utcnow():
            return AlarmControlPanelState.ARMING
        mode = alarm.get("mode")
        return MODES.get(mode) if isinstance(mode, str) else None

    def _exit_time(self):
        value = self.coordinator.data.alarm.get("exit_at")
        return dt_util.parse_datetime(value) if isinstance(value, str) else None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self):
        if self._cancel_countdown:
            self._cancel_countdown()
            self._cancel_countdown = None
        expires = self._exit_time()
        if expires and dt_util.as_utc(expires) > dt_util.utcnow():
            self._cancel_countdown = async_track_point_in_utc_time(
                self.hass, self._countdown_finished, expires
            )
        super()._handle_coordinator_update()

    @callback
    def _countdown_finished(self, now):
        self._cancel_countdown = None
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        if self._cancel_countdown:
            self._cancel_countdown()
        await super().async_will_remove_from_hass()

    async def _set_mode(self, mode, code):
        if self.code_arm_required and (
            not isinstance(code, str) or not code.isascii() or not code.isdecimal()
        ):
            raise ServiceValidationError("An alarm PIN is required")
        await self.coordinator.async_command(
            "PATCH", ("profiles", "active"), {"mode": mode, "pin": code}
        )

    async def async_alarm_disarm(self, code=None):
        await self._set_mode("disarmed", code)

    async def async_alarm_arm_home(self, code=None):
        await self._set_mode("dayArmed", code)

    async def async_alarm_arm_away(self, code=None):
        await self._set_mode("armed", code)

    async def async_alarm_arm_night(self, code=None):
        await self._set_mode("nightArmed", code)
