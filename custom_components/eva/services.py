"""Documented, on-demand home actions; no arbitrary API requests or polling."""

import json
import math

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util

from .api import EvaAuthError, EvaError
from .capabilities import validate_value
from .const import DOMAIN


def finite_number(value):
    """Do not accept booleans, strings or non-finite device settings."""
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise vol.Invalid("Expected a finite number")
    return value


def integer(value):
    value = finite_number(value)
    if value != int(value):
        raise vol.Invalid("Expected an integer")
    return int(value)


def timestamp(value):
    """Require a timezone so scheduled actions have an unambiguous instant."""
    if (
        not isinstance(value, str)
        or not (parsed := dt_util.parse_datetime(value))
        or parsed.tzinfo is None
    ):
        raise vol.Invalid("Expected an ISO timestamp including timezone")
    return value


TIME = vol.All(str, vol.Match(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$"))
ID = vol.All(str, vol.Length(min=1))
BASE = {vol.Required("config_entry_id"): ID}
DEVICE = {**BASE, vol.Required("device_id"): ID}
RANGE = {vol.Required("time_start"): timestamp, vol.Required("time_stop"): timestamp}
AGGREGATE = vol.In(("min", "max", "count", "first", "last", "sum", "mean", "median"))
ENERGY_SETTINGS = vol.All(
    vol.Schema(
        {
            **{
                vol.Optional(key): bool
                for key in (
                    "enabled",
                    "throttleByMainCircuitBreaker",
                    "throttleByGridTariffLevel",
                )
            },
            vol.Optional("throttlePriority"): vol.Any(
                None, vol.All(integer, vol.Range(min=1))
            ),
            vol.Optional("overrideUntil"): vol.Any(None, timestamp),
            vol.Optional("overrideDesiredState"): vol.Any(
                None, vol.In(("NUMERIC", "HEAT", "NO_HEAT", "CHARGE", "NO_CHARGE"))
            ),
            vol.Optional("overrideDesiredStateNumeric"): vol.Any(None, finite_number),
            **{
                vol.Optional(key): TIME
                for key in ("readyTime", "nightStart", "nightStop")
            },
            **{
                vol.Optional(key): vol.All(integer, vol.Range(min=0))
                for key in ("hoursToCharge", "hoursToHeat", "maxCurrent")
            },
            **{
                vol.Optional(key): finite_number
                for key in (
                    "setPoint",
                    "setPointAway",
                    "setPointAdjustmentNight",
                    "setPointAdjustmentPrice",
                )
            },
            vol.Optional("priorityTimes"): [TIME],
            vol.Optional("size"): vol.In(("SMALL", "MEDIUM", "LARGE")),
            vol.Optional("savingLevel"): vol.In(("LOW", "HIGH")),
        }
    ),
    vol.Length(min=1),
)

SCHEMAS = {
    "configure_gateway_updates": vol.Schema(
        {
            **BASE,
            vol.Required("enabled"): bool,
            vol.Required("hour_of_day"): vol.All(integer, vol.Range(min=0, max=23)),
        }
    ),
    "read_attribute": vol.Schema({**DEVICE, vol.Required("attribute"): ID}),
    "calibrate_lock": vol.Schema(DEVICE),
    "get_groups": vol.Schema(BASE),
    "set_group_attribute": vol.Schema(
        {
            **BASE,
            vol.Required("group_id"): vol.All(integer, vol.Range(min=1)),
            vol.Required("attribute"): ID,
            vol.Required("value"): vol.Any(bool, int, float, str),
        }
    ),
    "configure_energy_saver": vol.Schema(
        {**DEVICE, vol.Required("settings"): ENERGY_SETTINGS}
    ),
    "configure_home_energy_saver": vol.Schema(
        {
            **BASE,
            vol.Required("settings"): vol.All(
                vol.Schema(
                    {
                        vol.Optional("away"): vol.All(
                            vol.Schema(
                                {
                                    vol.Optional("enabled"): bool,
                                    vol.Optional("validFrom"): vol.Any(None, timestamp),
                                    vol.Optional("validTo"): vol.Any(None, timestamp),
                                }
                            ),
                            vol.Length(min=1),
                        ),
                        vol.Optional("throttleStrategy"): vol.In(
                            ("STATIC", "INCREMENTAL")
                        ),
                    }
                ),
                vol.Length(min=1),
            ),
        }
    ),
    "set_energy_saver_priority": vol.Schema(
        {**BASE, vol.Required("device_ids"): vol.All([ID], vol.Unique())}
    ),
    "get_energy_saver": vol.Schema(
        {
            **BASE,
            vol.Optional("device_id"): ID,
            vol.Required("kind"): vol.In(
                (
                    "settings",
                    "summary",
                    "plan",
                    "eventlog",
                    "prices",
                    "priority",
                    "home_eventlog",
                )
            ),
            vol.Optional("time_start"): timestamp,
            vol.Optional("time_stop"): timestamp,
            vol.Optional("count", default=20): vol.All(integer, vol.Range(min=1)),
            vol.Optional("start_time_key"): ID,
        }
    ),
    "get_measurements": vol.Schema(
        {
            **DEVICE,
            **RANGE,
            vol.Required("time_zone"): cv.time_zone,
            vol.Required("attribute"): ID,
            vol.Optional("aggregate"): AGGREGATE,
            vol.Optional("window_aggregate"): AGGREGATE,
            vol.Optional("window_duration"): vol.All(
                str, vol.Match(r"^[1-9][0-9]*(?:y|mo|w|d|h|m|s|ms)$")
            ),
            vol.Optional("window_time"): vol.In(("start", "stop")),
            vol.Optional("transform"): vol.In(
                ("electricityConsumption", "electricityConsumptionEstimate")
            ),
        }
    ),
    "get_charger_statistics": vol.Schema(
        {**DEVICE, **RANGE, vol.Required("time_zone"): cv.time_zone}
    ),
    "get_home_events": vol.Schema(
        {
            **BASE,
            vol.Optional("device_id"): ID,
            vol.Optional("mood_id"): ID,
            vol.Optional("offset", default=0): vol.All(integer, vol.Range(min=0)),
            vol.Optional("count", default=100): vol.All(integer, vol.Range(min=1)),
        }
    ),
}
READ_ACTIONS = {
    "get_groups",
    "get_energy_saver",
    "get_measurements",
    "get_charger_statistics",
    "get_home_events",
}


def get_device(coordinator, device_id):
    """Resolve only devices belonging to this loaded home."""
    device = coordinator.data.devices.get(device_id)
    if not device or device.get("resource") != "devices":
        raise ServiceValidationError("Select a device in this Eva home")
    if not coordinator.data.device_enabled(device):
        raise ServiceValidationError("This device feature is disabled for the Eva home")
    return device


def external_id(device):
    value = device.get("externalDeviceId")
    if not isinstance(value, str) or not value:
        raise ServiceValidationError("Configure Energy Saver for this device first")
    return value


def time_range(data):
    if "time_start" not in data or "time_stop" not in data:
        raise ServiceValidationError("Both time_start and time_stop are required")
    if dt_util.parse_datetime(data["time_start"]) >= dt_util.parse_datetime(
        data["time_stop"]
    ):
        raise ServiceValidationError("time_stop must be after time_start")
    return {"timeStart": data["time_start"], "timeStop": data["time_stop"]}


@callback
def async_setup_services(hass):
    """Home-wide actions require an administrator; automations may also call them."""

    async def handle(call):
        data = call.data
        entry = hass.config_entries.async_get_entry(data["config_entry_id"])
        if (
            entry is None
            or entry.domain != DOMAIN
            or entry.state is not ConfigEntryState.LOADED
        ):
            raise ServiceValidationError("Select a loaded Eva config entry")
        coordinator = entry.runtime_data
        if not coordinator.last_update_success:
            raise HomeAssistantError("Eva home is unavailable")
        try:
            return await async_handle_action(coordinator, call.service, data)
        except EvaAuthError as err:
            entry.async_start_reauth(hass)
            raise HomeAssistantError(str(err)) from err
        except EvaError as err:
            raise HomeAssistantError(str(err)) from err
        except (ValueError, vol.Invalid) as err:
            raise ServiceValidationError(str(err)) from err

    for name, schema in SCHEMAS.items():
        async_register_admin_service(
            hass,
            DOMAIN,
            name,
            handle,
            schema,
            supports_response=SupportsResponse.ONLY
            if name in READ_ACTIONS
            else SupportsResponse.NONE,
        )


async def async_handle_action(coordinator, action, data):
    """Validate each operation against the current snapshot before contacting Eva."""
    device_id = data.get("device_id")
    device = get_device(coordinator, device_id) if device_id is not None else None
    if action == "configure_gateway_updates":
        await coordinator.async_command(
            "PATCH",
            ("gateway", "automaticSoftwareUpdates"),
            {"enabled": data["enabled"], "hourOfDay": data["hour_of_day"]},
            requires_gateway=False,
        )
        return None
    if action == "get_groups":
        return {"groups": list(coordinator.data.groups.values())}
    if action == "set_group_attribute":
        group = coordinator.data.groups.get(data["group_id"])
        if (
            not coordinator.data.feature_enabled("groups")
            or not group
            or not group["deviceIds"]
        ):
            raise ServiceValidationError("Select an enabled, nonempty top-level group")
        value = data["value"]
        for member in group["deviceIds"]:
            target = get_device(coordinator, member)
            if (
                target.get("online") is not True
                or target.get("energySaverEnabled") is True
            ):
                raise ServiceValidationError(
                    "All group members must be online and allow manual control"
                )
            value = validate_value(target, data["attribute"], value)
        encoded = (
            value if isinstance(value, str) else json.dumps(value, allow_nan=False)
        )
        await coordinator.async_command(
            "POST",
            ("groups", str(data["group_id"]), "attributes", data["attribute"], encoded),
        )
        return None
    if action == "read_attribute":
        if (
            data["attribute"] not in device["attributes"]
            or device.get("external") is True
        ):
            raise ServiceValidationError(
                "Select a reported, non-external device attribute"
            )
        if device.get("online") is not True:
            raise ServiceValidationError("Wake the device before requesting a report")
        await coordinator.async_command(
            "POST", ("devices", device_id, "attributes", data["attribute"], "read")
        )
        return None
    if action == "calibrate_lock":
        model = f"{device.get('vendor', '')} {device.get('model', '')}".lower()
        if (
            "danalock" not in model
            or "v3" not in model
            or "locked" not in device["attributes"]
        ):
            raise ServiceValidationError(
                "Auto-calibration is documented only for Danalock V3"
            )
        if device.get("online") is not True:
            raise ServiceValidationError("The lock is unavailable")
        await coordinator.async_command(
            "POST", ("devices", device_id, "startAutoCalibration")
        )
        return None
    if action == "configure_energy_saver":
        identifier = device.get("externalDeviceId")
        if not identifier and device.get("eligibleForEnergySaver") is not True:
            raise ServiceValidationError("This device is not eligible for Energy Saver")
        parts = (
            "energySaver",
            "devices",
            external_id(device) if identifier else device_id,
            "settings",
        )
        await coordinator.async_command(
            "PATCH" if identifier else "POST",
            parts,
            data["settings"],
            requires_gateway=False,
        )
        return None
    if action == "configure_home_energy_saver":
        away = data["settings"].get("away", {})
        if away.get("validFrom") and away.get("validTo"):
            time_range({"time_start": away["validFrom"], "time_stop": away["validTo"]})
        await coordinator.async_command(
            "PATCH", ("energySaver",), data["settings"], requires_gateway=False
        )
        return None
    if action == "set_energy_saver_priority":
        identifiers = [
            external_id(get_device(coordinator, item)) for item in data["device_ids"]
        ]
        await coordinator.async_command(
            "PUT",
            ("energySaver", "throttlePriority"),
            {"throttlePriority": identifiers},
            requires_gateway=False,
        )
        return None
    params = {}
    if action == "get_energy_saver":
        kind = data["kind"]
        if kind in ("prices", "priority", "home_eventlog"):
            if device is not None:
                raise ServiceValidationError(
                    "This query applies to the home, not a device"
                )
            parts = (
                "energySaver",
                {
                    "prices": "electricityPrices",
                    "priority": "throttlePriority",
                    "home_eventlog": "topLevelEventlog",
                }[kind],
            )
        else:
            if device is None:
                raise ServiceValidationError("device_id is required for this query")
            parts = ("energySaver", "devices", external_id(device), kind)
        if kind in ("prices", "plan"):
            params = time_range(data)
        elif kind in ("eventlog", "home_eventlog"):
            params = {"count": data["count"]}
            if "start_time_key" in data:
                params["startTimeKey"] = data["start_time_key"]
    elif action in ("get_measurements", "get_charger_statistics"):
        params = {**time_range(data), "timeZone": data["time_zone"]}
        if action == "get_charger_statistics":
            if device.get("external") is not True or device.get("type") != "evCharger":
                raise ServiceValidationError("Select an external EV charger")
            parts = ("devices", device_id, "external", "evCharger", "stats")
            params["granularity"] = "hourly"
        else:
            if data["attribute"] not in device["attributes"]:
                raise ServiceValidationError(
                    "Select an attribute reported by this device"
                )
            parts = ("devices", "attributes", "measurements")
            params.update(deviceId=device_id, attribute=data["attribute"])
            for source, target in {
                "aggregate": "aggregate",
                "window_aggregate": "windowAggregate",
                "window_duration": "windowDuration",
                "window_time": "windowTime",
                "transform": "transform",
            }.items():
                if source in data:
                    params[target] = data[source]
    elif action == "get_home_events":
        parts = ("events",)
        params = {"offset": data["offset"], "count": data["count"]}
        if device_id is not None:
            params["deviceId"] = device_id
        if "mood_id" in data:
            if data["mood_id"] not in coordinator.data.moods:
                raise ServiceValidationError("Select a mood in this Eva home")
            params["moodId"] = data["mood_id"]
    else:
        raise ServiceValidationError("Unsupported Eva action")
    return {
        "data": await coordinator.client.async_get_data(
            coordinator.home_id, parts, params
        )
    }
