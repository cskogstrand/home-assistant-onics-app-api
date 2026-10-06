"""Zigbee closed percentages converted to HA open percentages."""

from homeassistant.components.cover import (
    CoverEntity,
    CoverEntityDescription,
    CoverEntityFeature,
)

from .entity import EvaEntity, async_discover

PARALLEL_UPDATES = 0
LIFT = "windowCoverLiftPercentage"
TILT = "windowCoverTiltPercentage"


async def async_setup_entry(hass, entry, async_add_entities):
    async_discover(
        entry,
        async_add_entities,
        lambda coordinator, device_id, device: (
            [
                EvaCover(
                    coordinator,
                    device_id,
                    CoverEntityDescription(key="cover", name=None),
                )
            ]
            if {LIFT, TILT} & device["attributes"].keys()
            else []
        ),
    )


class EvaCover(EvaEntity, CoverEntity):
    @property
    def available(self):
        return super().available and bool({LIFT, TILT} & self.attributes.keys())

    @property
    def supported_features(self):
        features = CoverEntityFeature(0)
        if LIFT in self.attributes:
            features |= (
                CoverEntityFeature.OPEN
                | CoverEntityFeature.CLOSE
                | CoverEntityFeature.SET_POSITION
            )
        if TILT in self.attributes:
            features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
            )
        return features

    def position(self, key):
        value = self.numeric_value(key)
        return round(100 - value) if value is not None and 0 <= value <= 100 else None

    @property
    def current_cover_position(self):
        return self.position(LIFT)

    @property
    def current_cover_tilt_position(self):
        return self.position(TILT)

    @property
    def is_closed(self):
        position = (
            self.current_cover_position
            if LIFT in self.attributes
            else self.current_cover_tilt_position
        )
        return None if position is None else position == 0

    async def async_open_cover(self, **kwargs):
        await self.async_write(LIFT, 0)

    async def async_close_cover(self, **kwargs):
        await self.async_write(LIFT, 100)

    async def async_set_cover_position(self, **kwargs):
        await self.async_write(LIFT, 100 - kwargs["position"])

    async def async_open_cover_tilt(self, **kwargs):
        await self.async_write(TILT, 0)

    async def async_close_cover_tilt(self, **kwargs):
        await self.async_write(TILT, 100)

    async def async_set_cover_tilt_position(self, **kwargs):
        await self.async_write(TILT, 100 - kwargs["tilt_position"])
