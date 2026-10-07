"""On/off, dimmable, color-temperature and HSV lights."""

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.exceptions import ServiceValidationError

from .capabilities import limits, platform_for
from .entity import EvaEntity, async_discover

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            [
                EvaLight(
                    coordinator,
                    device_id,
                    LightEntityDescription(key="light", name=None),
                )
            ]
            if any(platform_for(device, key) == "light" for key in device["attributes"])
            else []
        ),
    )


class EvaLight(EvaEntity, LightEntity):
    @property
    def available(self):
        return super().available and any(
            platform_for(self.device, key) == "light" for key in self.attributes
        )

    @property
    def supported_color_modes(self):
        modes = set()
        if {"colorHue", "colorSaturation"} <= self.attributes.keys():
            modes.add(ColorMode.HS)
        if "colorTemperature" in self.attributes:
            minimum, maximum, _ = limits(self.device, "colorTemperature")
            if minimum is not None and maximum is not None and 0 < minimum <= maximum:
                modes.add(ColorMode.COLOR_TEMP)
        return modes or {
            ColorMode.BRIGHTNESS if "dimLevel" in self.attributes else ColorMode.ONOFF
        }

    @property
    def color_mode(self):
        value = self.attribute_value("colorMode")
        mode = {"hsv": ColorMode.HS, "colorTemperature": ColorMode.COLOR_TEMP}.get(
            value if isinstance(value, str) else None
        )
        if mode in self.supported_color_modes:
            return mode
        if len(self.supported_color_modes) == 1:
            return next(iter(self.supported_color_modes))
        return ColorMode.UNKNOWN

    @property
    def is_on(self):
        return self.boolean_value("on")

    @property
    def brightness(self):
        value = self.numeric_value("dimLevel")
        return (
            round(value * 255 / 100)
            if value is not None and 0 <= value <= 100
            else None
        )

    @property
    def color_temp_kelvin(self):
        value = self.numeric_value("colorTemperature")
        return round(value) if value is not None and value > 0 else None

    @property
    def min_color_temp_kelvin(self):
        value = (
            limits(self.device, "colorTemperature")[0]
            if "colorTemperature" in self.attributes
            else None
        )
        return (
            round(value)
            if value is not None and value > 0
            else super().min_color_temp_kelvin
        )

    @property
    def max_color_temp_kelvin(self):
        value = (
            limits(self.device, "colorTemperature")[1]
            if "colorTemperature" in self.attributes
            else None
        )
        return (
            round(value)
            if value is not None and value > 0
            else super().max_color_temp_kelvin
        )

    @property
    def hs_color(self):
        hue, saturation = (
            self.numeric_value("colorHue"),
            self.numeric_value("colorSaturation"),
        )
        return (
            (hue, saturation)
            if hue is not None
            and saturation is not None
            and 0 <= hue <= 360
            and 0 <= saturation <= 100
            else None
        )

    async def async_turn_on(self, **kwargs):
        if kwargs.get("brightness") == 0:
            await self.async_turn_off()
            return
        # Reject a compound request before applying any part of it.
        writes = []
        if "brightness" in kwargs:
            writes.append(("dimLevel", max(1, round(kwargs["brightness"] * 100 / 255))))
        if "color_temp_kelvin" in kwargs:
            if ColorMode.COLOR_TEMP not in self.supported_color_modes:
                raise ServiceValidationError("Color temperature control is unavailable")
            writes.append(("colorTemperature", round(kwargs["color_temp_kelvin"])))
        if "hs_color" in kwargs:
            hue, saturation = kwargs["hs_color"]
            writes.extend(
                (("colorHue", round(hue)), ("colorSaturation", round(saturation)))
            )
        if "on" in self.attributes:
            writes.append(("on", True))
        elif not writes:
            raise ServiceValidationError("This device has no on/off capability")
        self.validate_writes(writes)
        for key, value in writes:
            if key == "on" and len(writes) > 1 and self.is_on is True:
                continue
            await self.async_write(key, value)

    async def async_turn_off(self, **kwargs):
        await self.async_write("on", False)
