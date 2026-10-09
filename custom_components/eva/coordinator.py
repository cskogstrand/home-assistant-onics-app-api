"""Share a single SSE subscription between the selected home's entities."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import aclosing, suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryError,
    HomeAssistantError,
)
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EvaAuthError, EvaClient, EvaError, EvaRateLimitError
from .const import (
    CONF_HOME_ID,
    CONF_SSE_CLIENT_ID,
    DOMAIN,
    INITIAL_SNAPSHOT_TIMEOUT,
    STREAM_IDLE_TIMEOUT,
)
from .events import (
    ACTION_SUCCESS_EVENTS,
    EVENT_TYPE,
    STREAM_EVENTS,
    action_failed,
    event_data,
)
from .state import HomeState, InvalidEvent

_LOGGER = logging.getLogger(__name__)

type EvaConfigEntry = ConfigEntry[EvaCoordinator]


class EvaCoordinator(DataUpdateCoordinator[HomeState]):
    """Share SSE state plus the separate external-charger status endpoint."""

    def __init__(
        self, hass: HomeAssistant, entry: EvaConfigEntry, client: EvaClient
    ) -> None:
        """Keep one client ID and one stream per entry."""
        super().__init__(
            hass, _LOGGER, name=DOMAIN, config_entry=entry, always_update=False
        )
        self.client = client
        self.home_id = entry.data[CONF_HOME_ID]
        self.client_id = entry.data[CONF_SSE_CLIENT_ID]
        self.data = HomeState(self.home_id, {}, False)
        self.last_update_success = False
        self._task: asyncio.Task[None] | None = None
        self._ready: asyncio.Future[None] = hass.loop.create_future()
        self._last_event_id: str | None = None
        self._command_listeners: set[Callable[[dict], None]] = set()
        self._pending_commands: dict[tuple[str, ...], asyncio.Future[str | None]] = {}
        self.external_status: dict[str, dict | None] = {}
        self._charger_task: asyncio.Task | None = None

    async def _async_poll_chargers(self) -> None:
        """Poll external chargers once per minute, isolated from Zigbee availability."""
        try:
            await asyncio.shield(self._ready)
        except EvaError, ConfigEntryError:
            return
        while True:
            delay = 60
            for device_id, device in tuple(self.data.devices.items()):
                if (
                    device.get("external") is not True
                    or device.get("type") != "evCharger"
                ):
                    continue
                rate_limited = False
                try:
                    status = await self.client.async_get_charger_status(
                        self.home_id, device_id
                    )
                except EvaAuthError:
                    self.external_status[device_id] = None
                    self.async_update_listeners()
                    self.config_entry.async_start_reauth(self.hass)
                    return
                except EvaRateLimitError as err:
                    status = None
                    delay = max(delay, err.retry_after)
                    rate_limited = True
                except EvaError:
                    status = None
                if device_id in self.data.devices:
                    self.external_status[device_id] = status
                    self.async_update_listeners()
                if rate_limited:
                    break
            await asyncio.sleep(delay)

    async def async_command(
        self,
        method: str,
        parts: tuple[str, ...],
        payload: dict | None = None,
        *,
        requires_gateway: bool = True,
    ) -> bool:
        """Send immediately; return False when a newer resource command supersedes it."""
        if parts[0] == "moods" and not self.data.feature_enabled("moods"):
            raise HomeAssistantError("Moods are disabled for this Eva home")
        if parts[0] in {"devices", "groups"}:
            device_id = f"group:{parts[1]}" if parts[0] == "groups" else parts[1]
            device = self.data.devices.get(device_id)
            if device is not None and not self.data.device_enabled(device):
                raise HomeAssistantError("This feature is disabled for the Eva home")
        if not self.last_update_success or (
            requires_gateway
            and not self.data.gateway_online
            and "external" not in parts
        ):
            raise HomeAssistantError("Eva home is unavailable")
        action_id = None
        early_results: dict[str, str] = {}
        result = self.hass.loop.create_future()
        resource = parts[:3] if parts[:2] == ("energySaver", "devices") else parts[:2]
        previous = self._pending_commands.get(resource)
        if previous is not None and not previous.done():
            previous.set_result(None)
        self._pending_commands[resource] = result

        def receive(event: dict) -> None:
            if result.done():
                return
            event_type = event.get("eventType", "")
            event_id = event.get("actionId")
            if not isinstance(event_id, str) or not (
                event_type in ACTION_SUCCESS_EVENTS or action_failed(event_type)
            ):
                return
            if action_id is None:
                early_results[event_id] = event_type
            elif event_id == action_id:
                result.set_result(event_type)

        self._command_listeners.add(receive)
        try:
            action_id = await self.client.async_command(
                self.home_id, method, parts, payload
            )
            if self._pending_commands.get(resource) is not result:
                return False
            if not action_id or "external" in parts:
                return True
            if action_id in early_results:
                result.set_result(early_results[action_id])
            async with asyncio.timeout(30):
                event_type = await result
            if event_type is None or self._pending_commands.get(resource) is not result:
                return False
            if action_failed(event_type):
                raise HomeAssistantError("Eva could not complete the command")
            return True
        except EvaAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except EvaError as err:
            raise HomeAssistantError(str(err)) from err
        except TimeoutError as err:
            raise HomeAssistantError(
                "Eva accepted the command but did not confirm it within 30 seconds"
            ) from err
        finally:
            if self._pending_commands.get(resource) is result:
                del self._pending_commands[resource]
            self._command_listeners.discard(receive)
            result.cancel()

    async def _async_setup(self) -> None:
        """Start the stream; HA cancels background tasks on shutdown."""
        self._task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_listen(),
            "Eva SSE",
            eager_start=False,
        )
        self._charger_task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_poll_chargers(),
            "Eva external chargers",
            eager_start=False,
        )

    async def _async_update_data(self) -> HomeState:
        """Wait for a real snapshot during setup; never turn stale data available."""
        try:
            async with asyncio.timeout(INITIAL_SNAPSHOT_TIMEOUT):
                await asyncio.shield(self._ready)
        except EvaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EvaError as err:
            raise UpdateFailed(str(err)) from err
        if not self.last_update_success:
            raise UpdateFailed("Eva stream is unavailable")
        return self.data

    async def _async_listen(self) -> None:
        """Reconnect after server closure or failure; stop on auth failure."""
        backoff = 1.0
        while True:
            delay = max(backoff, self.client.retry_seconds)
            has_snapshot = False
            try:
                async with (
                    asyncio.timeout(INITIAL_SNAPSHOT_TIMEOUT) as snapshot_timeout,
                    aclosing(
                        self.client.async_events(
                            self.home_id,
                            self.client_id,
                            self._last_event_id,
                        )
                    ) as events,
                ):
                    while True:
                        async with asyncio.timeout(STREAM_IDLE_TIMEOUT):
                            event = await anext(events, None)
                        if event is None:
                            break
                        event_type = event["eventType"]
                        if event_type == "killClient":
                            error = ConfigEntryError(
                                "Eva SSE received killClient; the server requested "
                                "this client to stop. Automatic reconnect stopped; "
                                "reload the integration to retry"
                            )
                            self.async_set_update_error(error)
                            if not self._ready.done():
                                self._ready.set_exception(error)
                            return
                        if event_type == "resetClient":
                            raise InvalidEvent(
                                "Eva SSE received resetClient; discarding the replay "
                                "cursor and requesting a fresh home snapshot"
                            )
                        if "home" in event:
                            has_snapshot = True
                        state = self.data.apply(event)
                        if event_type == "homeFeatures" and not has_snapshot:
                            self.data = state
                        if has_snapshot:
                            if "home" in event:
                                _LOGGER.debug(
                                    "Eva SSE home snapshot received; stream active"
                                )
                            snapshot_timeout.reschedule(None)
                            if "home" in event or event_type in {
                                "deviceDeleted",
                                "deviceAddFailed",
                                "groupDeleted",
                                "homeDeleted",
                            }:
                                self._async_sync_devices(state)
                            if state != self.data or not self.last_update_success:
                                self.async_set_updated_data(state)
                            for listener in tuple(self._command_listeners):
                                listener(event)
                            if event_type not in STREAM_EVENTS:
                                self.hass.bus.async_fire(
                                    EVENT_TYPE,
                                    {
                                        "config_entry_id": self.config_entry.entry_id,
                                        "home_id": self.home_id,
                                        **event_data(event),
                                    },
                                )
                            backoff = 1.0
                            if not self._ready.done():
                                self._ready.set_result(None)
                        if has_snapshot and isinstance(event.get("id"), str):
                            self._last_event_id = event["id"]
                # The server normally closes the stream after ten minutes.
                if not has_snapshot:
                    raise EvaError("Eva SSE stream closed before a home snapshot")
                _LOGGER.debug(
                    "Eva SSE stream closed; reconnecting automatically "
                    "(API streams normally close after 10 minutes)"
                )
            except EvaAuthError as err:
                self.async_set_update_error(
                    ConfigEntryAuthFailed(
                        f"{err}; automatic reconnect stopped; reauthentication required"
                    )
                )
                if not self._ready.done():
                    self._ready.set_exception(err)
                else:
                    self.config_entry.async_start_reauth(self.hass)
                return
            except TimeoutError:
                if has_snapshot:
                    _LOGGER.debug(
                        "Eva SSE received no events for %s seconds; reconnecting "
                        "automatically (keepAlive is normally sent every 5 seconds)",
                        STREAM_IDLE_TIMEOUT,
                    )
                else:
                    self.async_set_update_error(
                        UpdateFailed(
                            "Eva SSE timed out before receiving a home snapshot; "
                            "reconnecting automatically"
                        )
                    )
            except (EvaError, InvalidEvent) as err:
                self.async_set_update_error(
                    UpdateFailed(f"{err}; reconnecting automatically")
                )
                if isinstance(err, InvalidEvent):
                    self._last_event_id = None
                if isinstance(err, EvaRateLimitError):
                    delay = max(delay, err.retry_after)
            delay = max(delay, self.client.retry_seconds)
            _LOGGER.debug("Reconnecting Eva SSE stream in %s seconds", delay)
            await asyncio.sleep(delay)
            backoff = min(max(backoff * 2, delay), 60.0)

    def _async_sync_devices(self, state: HomeState) -> None:
        """Reconcile this entry's registry only after an authoritative update."""
        self.external_status = {
            key: value
            for key, value in self.external_status.items()
            if key in state.devices
        }
        identifiers = {
            (DOMAIN, f"{self.config_entry.unique_id}:{device_id}")
            for device_id in state.devices
        }
        registry = dr.async_get(self.hass)
        areas = ar.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            if not identifiers.intersection(device.identifiers):
                registry.async_remove_device(device.id)
        for device_id, device in state.devices.items():
            registered = registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, f"{self.config_entry.unique_id}:{device_id}")},
                name=device.get("name"),
                manufacturer=device.get("vendor"),
                model=device.get("model"),
                sw_version=device.get("softwareVersion"),
                hw_version=device.get("hardwareVersion"),
                suggested_area=device.get("room_name"),
            )
            if room_name := device.get("room_name"):
                area = areas.async_get_or_create(room_name)
                # Suggested areas only apply until HA has assigned an area.
                registry.async_update_device(registered.id, area_id=area.id)

    async def async_shutdown(self) -> None:
        """Cancel and await the stream, closing its HTTP response on every exit."""
        if self._charger_task is not None:
            self._charger_task.cancel()
            with suppress(asyncio.CancelledError, EvaError, ConfigEntryError):
                await self._charger_task
            self._charger_task = None
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if not self._ready.done():
            self._ready.cancel()
        elif not self._ready.cancelled():
            self._ready.exception()
        await super().async_shutdown()
