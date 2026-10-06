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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EvaAuthError, EvaClient, EvaError, EvaRateLimitError
from .const import (
    CONF_HOME_ID,
    CONF_SSE_CLIENT_ID,
    DOMAIN,
    INITIAL_SNAPSHOT_TIMEOUT,
    STREAM_IDLE_TIMEOUT,
    STREAM_REFRESH_INTERVAL,
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
        self, method: str, parts: tuple[str, ...], payload: dict | None = None
    ) -> None:
        """Wait for an action result, including results arriving before HTTP returns."""
        if not self.last_update_success or (
            not self.data.gateway_online and "external" not in parts
        ):
            raise HomeAssistantError("Eva home is unavailable")
        action_id = None
        early_results: dict[str, str] = {}
        result = self.hass.loop.create_future()

        def receive(event: dict) -> None:
            event_type = event.get("eventType", "")
            event_id = event.get("actionId")
            if not isinstance(event_id, str) or not (
                event_type
                in {
                    "deviceAttributeChanged",
                    "groupAttributeChanged",
                    "deviceUpdated",
                    "deviceIdentified",
                    "deviceSoftwareUpdateAssigned",
                    "activeProfileUpdated",
                    "moodActivated",
                    "actionTimeout",
                }
                or "Failed" in event_type
            ):
                return
            if action_id is None:
                early_results[event_id] = event_type
            elif event_id == action_id and not result.done():
                result.set_result(event_type)

        self._command_listeners.add(receive)
        try:
            action_id = await self.client.async_command(
                self.home_id, method, parts, payload
            )
            if not action_id or "external" in parts:
                return
            if action_id in early_results:
                result.set_result(early_results[action_id])
            async with asyncio.timeout(30):
                event_type = await result
            if event_type == "actionTimeout" or "Failed" in event_type:
                raise HomeAssistantError("Eva could not complete the command")
        except EvaAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError("Eva authentication rejected") from err
        except EvaError as err:
            raise HomeAssistantError(str(err)) from err
        except TimeoutError as err:
            raise HomeAssistantError(
                "Eva accepted the command but did not confirm it within 30 seconds"
            ) from err
        finally:
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
            raise ConfigEntryAuthFailed("Eva authentication rejected") from err
        except EvaError as err:
            raise UpdateFailed(str(err)) from err
        if not self.last_update_success:
            raise UpdateFailed("Eva stream is unavailable")
        return self.data

    async def _async_listen(self) -> None:
        """Refresh before expiry and reconnect on failure; stop on auth failure."""
        backoff = 1.0
        while True:
            delay = max(backoff, self.client.retry_seconds)
            has_snapshot = False
            try:
                async with (
                    asyncio.timeout(STREAM_REFRESH_INTERVAL) as refresh_timeout,
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
                                "Eva closed this client; check access before reloading"
                            )
                            self.async_set_update_error(error)
                            if not self._ready.done():
                                self._ready.set_exception(error)
                            return
                        if event_type == "resetClient":
                            raise InvalidEvent("Eva requested a fresh snapshot")
                        if "home" in event:
                            has_snapshot = True
                        state = self.data.apply(event)
                        if has_snapshot:
                            snapshot_timeout.reschedule(None)
                            if "home" in event or event_type in {
                                "deviceDeleted",
                                "groupDeleted",
                                "homeDeleted",
                            }:
                                self._async_remove_deleted_devices(state)
                            if state != self.data or not self.last_update_success:
                                self.async_set_updated_data(state)
                            for listener in tuple(self._command_listeners):
                                listener(event)
                            backoff = 1.0
                            if not self._ready.done():
                                self._ready.set_result(None)
                        if has_snapshot and isinstance(event.get("id"), str):
                            self._last_event_id = event["id"]
                raise EvaError("Eva stream closed")
            except EvaAuthError as err:
                self.async_set_update_error(
                    ConfigEntryAuthFailed("Eva authentication rejected")
                )
                if not self._ready.done():
                    self._ready.set_exception(err)
                else:
                    self.config_entry.async_start_reauth(self.hass)
                return
            except (EvaError, InvalidEvent, TimeoutError) as err:
                if isinstance(err, TimeoutError) and refresh_timeout.expired():
                    continue
                self.async_set_update_error(
                    UpdateFailed(
                        str(err)
                        or (
                            "Eva event stream went silent"
                            if has_snapshot
                            else "Timed out waiting for a home snapshot"
                        )
                    )
                )
                if isinstance(err, InvalidEvent):
                    self._last_event_id = None
                if isinstance(err, EvaRateLimitError):
                    delay = max(delay, err.retry_after)
            delay = max(delay, self.client.retry_seconds)
            await asyncio.sleep(delay)
            backoff = min(max(backoff * 2, delay), 60.0)

    def _async_remove_deleted_devices(self, state: HomeState) -> None:
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
        for device in dr.async_entries_for_config_entry(
            registry, self.config_entry.entry_id
        ):
            if not identifiers.intersection(device.identifiers):
                registry.async_remove_device(device.id)
        for device_id, device in state.devices.items():
            registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, f"{self.config_entry.unique_id}:{device_id}")},
                name=device.get("name"),
                manufacturer=device.get("vendor"),
                model=device.get("model"),
                sw_version=device.get("softwareVersion"),
                hw_version=device.get("hardwareVersion"),
                suggested_area=device.get("room_name"),
            )

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
