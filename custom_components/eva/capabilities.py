"""Documented Eva attributes, independent of device vendor or model.

Source: https://onicsas.github.io/home-hla-docs/#attributes
Unknown attributes are read-only; a current value never implies write access.
"""

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Attribute:
    """The API contract used for discovery, units and command validation."""

    platform: str = "sensor"
    kind: type = float
    unit: str | None = None
    device_class: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1
    options: tuple[str | int, ...] = ()
    diagnostic: bool = False


ATTRIBUTES: dict[str, Attribute] = {}


def _add(names: str, **kwargs: Any) -> None:
    for name in names.split():
        ATTRIBUTES[name] = Attribute(**kwargs)


_add("charging", platform="switch", kind=bool)
_add("carPluggedIn", platform="binary_sensor", kind=bool, device_class="plug")
_add("currentPower", unit="W", device_class="power")


_add(
    "temperature airTemperature floorTemperature", unit="°C", device_class="temperature"
)
_add(
    "relativeHumidity relativeHumidityMin relativeHumidityMax",
    unit="%",
    device_class="humidity",
)
_add("pressure pressureMin pressureMax", unit="Pa", device_class="pressure")
_add("illuminance illuminanceMin illuminanceMax", unit="lx", device_class="illuminance")
_add("co2Concentration", unit="ppm", device_class="carbon_dioxide")
_add("tvocConcentration", unit="ppm", device_class="volatile_organic_compounds_parts")
_add("batteryPercentage", unit="%", device_class="battery", diagnostic=True)
_add("rssi", unit="dBm", device_class="signal_strength", diagnostic=True)
_add(
    "acNeutralCurrent phase1current phase2current phase3current",
    unit="A",
    device_class="current",
)
_add("acTotalPower electricityConsumption", unit="W", device_class="power")
_add("acTotalReactivePower", unit="var", device_class="reactive_power")
_add("acTotalApparentPower", unit="VA", device_class="apparent_power")
for _prefix in ("ac", "dc"):
    for _quantity, _unit, _class in (
        ("Voltage", "V", "voltage"),
        ("Current", "A", "current"),
        ("Power", "W", "power"),
    ):
        _add(
            " ".join(f"{_prefix}{_quantity}{suffix}" for suffix in ("", "Min", "Max")),
            unit=_unit,
            device_class=_class,
        )
_add("electricityConsumptionSummary", unit="Wh", device_class="energy")
_add(
    "electricityConsumptionCurrentHourMeasured electricityConsumptionCurrentHourEstimate",
    unit="kWh",
    device_class="energy",
)
_add("waterConsumptionSummary", unit="m³", device_class="water")
_add("waterConsumption", unit="m³/h", device_class="volume_flow_rate")
_add(
    "electricityMeterSerialNumber statusType statusMessage statusDetails colorMode",
    kind=str,
)

for _names, _class in (
    ("lowBattery", "battery"),
    ("batteryDefect acFault boltJammed", "problem"),
    ("tampered", "tamper"),
    ("movement", "motion"),
    ("presenceIndication", "occupancy"),
    ("open", "opening"),
    ("fireIndication", "smoke"),
    ("waterOverflowIndication", "moisture"),
    ("carbonMonoxideIndication", "carbon_monoxide"),
    ("vibration", "vibration"),
    ("heating", "heat"),
    (
        "cookingIndication fallOrConcussion panic emergency glassBreakageDetected",
        "safety",
    ),
):
    _add(_names, platform="binary_sensor", kind=bool, device_class=_class)

_add("on", platform="switch", kind=bool)
_add(
    "childLock relock frostAndHeatGuard showTemperature roomThermometer showTvocConcentration roomTvocConcentration relativeHumidityGuard partOfAlarmSystem moodButton2Enabled",
    platform="switch",
    kind=bool,
)
_add("locked", platform="lock", kind=bool)
_add("dimLevel", platform="light", minimum=1, maximum=100, kind=int, unit="%")
_add("colorTemperature", platform="light", kind=int, unit="K")
_add("colorHue", platform="light", kind=int, minimum=0, maximum=360)
_add("colorSaturation", platform="light", kind=int, minimum=0, maximum=100, unit="%")
_add("setpoint", platform="climate", kind=int, unit="°C")
_add(
    "windowCoverLiftPercentage windowCoverTiltPercentage",
    platform="cover",
    kind=int,
    minimum=0,
    maximum=100,
    unit="%",
)
_add("windowCoverLiftPosition", platform="number", kind=int, unit="cm")
_add("windowCoverTiltPosition", platform="number", kind=int, unit="°")

for _name, _minimum, _maximum, _step, _unit in (
    ("minutesUntilOff", 1, 1440, 1, "min"),
    ("onTime", -1, 6553, 1, "s"),
    ("installedLoad", 0, 9999, 1, "W"),
    ("regulatorTime", 1, 20, 1, "min"),
    ("maxFloorTemperature", 20, 40, 1, "°C"),
    ("temperatureCalibration", -10, 10, 1, "°C"),
    ("sensitivityLevel", None, None, 1, None),
    ("noPresenceDelay", 1, 65534, 1, "s"),
    ("autoRelockTime", 0, 2147483647, 1, "s"),
    ("powerLevel", 1, 100, 5, "%"),
    ("chargeCurrent", None, None, 1, "A"),
    ("temperatureThresholdMin", -273, 1000, 1, "°C"),
    ("temperatureThresholdMax", -273, 1000, 1, "°C"),
    ("relativeHumidityThresholdMin", 0, 100, 1, "%"),
    ("relativeHumidityThresholdMax", 0, 100, 1, "%"),
    ("regulatorFallback", 0, 100, 10, "%"),
    ("electricityConsumptionThreshold", 1, 99999, 1, "W"),
):
    _add(
        _name,
        platform="number",
        kind=float if _name == "temperatureCalibration" else int,
        minimum=_minimum,
        maximum=_maximum,
        step=_step,
        unit=_unit,
    )

for _name, _options in (
    ("startupOnOff", ("off", "on", "previous", "toggle")),
    ("mode", ("thermostat", "regulator")),
    ("sensor", ()),
    (
        "lockMode",
        (
            "home_and_manual_lock",
            "home_and_auto_lock",
            "away_and_manual_lock",
            "away_and_auto_lock",
        ),
    ),
    ("doorLockVolume", ("off", "low", "high")),
):
    _add(_name, platform="select", kind=str, options=_options)
_add("displayText", platform="text", kind=str, minimum=0, maximum=14)
_add("moodButton1 moodButton2 moodButton3 moodButton4", platform="text", kind=str)


def number(value: Any) -> float | None:
    """Reject booleans, numeric strings, NaN and infinity."""
    try:
        if type(value) in (int, float) and math.isfinite(value):
            return value
    except OverflowError:
        pass
    return None


def is_light(device: dict) -> bool:
    """Use capabilities first, device type only for an on/off-only lamp."""
    device_type = device.get("type")
    device_type = device_type.lower() if isinstance(device_type, str) else ""
    return bool(
        {"dimLevel", "colorTemperature", "colorHue", "colorSaturation"}
        & device["attributes"].keys()
    ) or (device_type.startswith("light") or device_type == "dimmer")


def limits(device: dict, key: str) -> tuple[float | None, float | None, float]:
    """Honor per-device bounds and calibration resolution."""
    spec = ATTRIBUTES[key]
    attribute = device["attributes"][key]
    options = attribute.get("options")
    numeric_options = (
        [number(value) for value in options] if isinstance(options, list) else []
    )
    minimum, maximum = spec.minimum, spec.maximum
    if numeric_options and all(value is not None for value in numeric_options):
        minimum, maximum = min(numeric_options), max(numeric_options)
    minimum = number(attribute.get("minValue")) if "minValue" in attribute else minimum
    maximum = number(attribute.get("maxValue")) if "maxValue" in attribute else maximum
    step = (
        0.1
        if key == "temperatureCalibration" and "setpoint" in device["attributes"]
        else spec.step
    )
    if number(attribute.get("step")) is not None and attribute["step"] > 0:
        step = attribute["step"]
    return minimum, maximum, step


def options(device: dict, key: str) -> list[str]:
    """Use only explicitly supported enum values."""
    values = device["attributes"][key].get("options", ATTRIBUTES[key].options)
    return (
        [value for value in values if isinstance(value, str)]
        if isinstance(values, (list, tuple))
        else []
    )


def platform_for(device: dict, key: str) -> str | None:
    """Map every reported attribute once; compound entities own their controls."""
    spec = ATTRIBUTES.get(key)
    if spec is None:
        return "sensor"
    if key == "charging" and not (
        device.get("external") is True and device.get("type") == "evCharger"
    ):
        return "sensor"
    if key == "on":
        if "setpoint" in device["attributes"]:
            return None
        return "light" if is_light(device) else "switch"
    if spec.platform == "number":
        minimum, maximum, _ = limits(device, key)
        if minimum is None or maximum is None or minimum > maximum:
            return "sensor"
    if spec.platform == "select" and not options(device, key):
        return "sensor"
    return spec.platform


def validate_value(device: dict, key: str, value: Any) -> Any:
    """Enforce the documented write contract before any request leaves HA."""
    spec = ATTRIBUTES.get(key)
    if (
        spec is None
        or spec.platform in {"sensor", "binary_sensor"}
        or key not in device["attributes"]
    ):
        raise ValueError("Attribute is not writable")
    if spec.kind is bool:
        if type(value) is not bool:
            raise ValueError("Expected a boolean")
    elif spec.kind is str:
        if not isinstance(value, str):
            raise ValueError("Expected text")
        if spec.platform == "select" and value not in options(device, key):
            raise ValueError("Unsupported option")
        if (
            spec.platform == "text"
            and spec.maximum is not None
            and len(value) > spec.maximum
        ):
            raise ValueError("Text is too long")
    else:
        if number(value) is None:
            raise ValueError("Expected a finite number")
        minimum, maximum, step = limits(device, key)
        if (minimum is not None and value < minimum) or (
            maximum is not None and value > maximum
        ):
            raise ValueError("Value outside supported range")
        # Eva's powerLevel accepts 1 as its minimum as well as 5, 10, ..., 100.
        origin = 0 if key == "powerLevel" else minimum or 0
        if not (key == "powerLevel" and value == 1) and not math.isclose(
            (value - origin) / step, round((value - origin) / step), abs_tol=1e-7
        ):
            raise ValueError("Value does not match supported step")
        if spec.kind is int:
            if not float(value).is_integer() and float(step).is_integer():
                raise ValueError("Expected an integer")
            if float(value).is_integer():
                value = int(value)
    allowed = device["attributes"][key].get("options")
    if isinstance(allowed, list) and allowed and value not in allowed:
        raise ValueError("Unsupported option")
    return value
