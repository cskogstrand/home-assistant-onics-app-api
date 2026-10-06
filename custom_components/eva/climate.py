"""Eva thermostat and virtual-heater capabilities."""

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.exceptions import ServiceValidationError

from .capabilities import limits
from .entity import EvaAttributeEntity, async_discover

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            [
                EvaClimate(
                    coordinator,
                    device_id,
                    ClimateEntityDescription(key="setpoint", name=None),
                )
            ]
            if "setpoint" in device["attributes"]
            else []
        ),
    )


class EvaClimate(EvaAttributeEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    @property
    def supported_features(self):
        features = ClimateEntityFeature.TARGET_TEMPERATURE
        if "on" in self.attributes:
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        return features

    @property
    def hvac_modes(self):
        return (
            [HVACMode.HEAT, HVACMode.OFF]
            if "on" in self.attributes
            else [HVACMode.HEAT]
        )

    @property
    def hvac_mode(self):
        if "on" not in self.attributes:
            return HVACMode.HEAT
        value = self.boolean_value("on")
        return None if value is None else HVACMode.HEAT if value else HVACMode.OFF

    @property
    def hvac_action(self):
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        value = self.boolean_value("heating")
        return (
            None if value is None else HVACAction.HEATING if value else HVACAction.IDLE
        )

    @property
    def current_temperature(self):
        sensor = self.attribute_value("sensor")
        if sensor is not None and not isinstance(sensor, str):
            return None
        if sensor == "floorTemperature":
            return self.numeric_value("floorTemperature")
        if sensor in {"externalAirTemperature", "externalAirWithFloorGuard"}:
            return self.numeric_value("externalAirTemperature")
        if (
            sensor in {"regulatorWithoutFloorGuard", "regulatorWithFloorGuard"}
            or self.attribute_value("mode") == "regulator"
        ):
            return None
        for key in ("airTemperature", "temperature", "floorTemperature"):
            if key in self.attributes:
                return self.numeric_value(key)
        return None

    @property
    def target_temperature(self):
        return self.numeric_value("setpoint")

    @property
    def min_temp(self):
        value = (
            limits(self.device, "setpoint")[0]
            if "setpoint" in self.attributes
            else None
        )
        return value if value is not None else super().min_temp

    @property
    def max_temp(self):
        value = (
            limits(self.device, "setpoint")[1]
            if "setpoint" in self.attributes
            else None
        )
        return value if value is not None else super().max_temp

    @property
    def target_temperature_step(self):
        return (
            limits(self.device, "setpoint")[2] if "setpoint" in self.attributes else 1
        )

    async def async_set_temperature(self, **kwargs):
        writes = [("setpoint", kwargs[ATTR_TEMPERATURE])]
        if "hvac_mode" in kwargs:
            mode = kwargs["hvac_mode"]
            if mode not in self.hvac_modes:
                raise ServiceValidationError("Unsupported HVAC mode")
            if "on" in self.attributes:
                writes.append(("on", mode == HVACMode.HEAT))
        self.validate_writes(writes)
        for key, value in writes:
            await self.async_write(key, value)

    async def async_set_hvac_mode(self, hvac_mode):
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError("Unsupported HVAC mode")
        if "on" in self.attributes:
            await self.async_write("on", hvac_mode == HVACMode.HEAT)

    async def async_turn_on(self):
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self):
        await self.async_set_hvac_mode(HVACMode.OFF)
