"""Share a single SSE subscription between the selected home's entities."""

import asyncio
import logging
from contextlib import aclosing, suppress

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import OnicsAuthError, OnicsClient, OnicsError, OnicsRateLimitError
from .const import CONF_HOME_ID, CONF_SSE_CLIENT_ID, DOMAIN, STREAM_IDLE_TIMEOUT
from .state import HomeState, InvalidEvent

_LOGGER = logging.getLogger(__name__)

type OnicsConfigEntry = ConfigEntry[OnicsCoordinator]


class OnicsCoordinator(DataUpdateCoordinator[HomeState]):
    """Replace snapshots and publish partial updates without polling."""

    def __init__(
        self, hass: HomeAssistant, entry: OnicsConfigEntry, client: OnicsClient
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

    async def _async_setup(self) -> None:
        """Start the stream; HA cancels background tasks on shutdown."""
        self._task = self.config_entry.async_create_background_task(
            self.hass,
            self._async_listen(),
            "Onics SSE",
            eager_start=False,
        )

    async def _async_update_data(self) -> HomeState:
        """Wait for a real snapshot during setup; never turn stale data available."""
        try:
            async with asyncio.timeout(35):
                await asyncio.shield(self._ready)
        except OnicsAuthError as err:
            raise ConfigEntryAuthFailed("Onics authentication rejected") from err
        except OnicsError as err:
            raise UpdateFailed(str(err)) from err
        if not self.last_update_success:
            raise UpdateFailed("Onics stream is unavailable")
        return self.data

    async def _async_listen(self) -> None:
        """Reconnect after EOF, silence or network failure; stop on auth failure."""
        backoff = 1.0
        while True:
            delay = max(backoff, self.client.retry_seconds)
            has_snapshot = False
            try:
                async with (
                    asyncio.timeout(35) as snapshot_timeout,
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
                                "Onics closed this client; check access before reloading"
                            )
                            self.async_set_update_error(error)
                            if not self._ready.done():
                                self._ready.set_exception(error)
                            return
                        if event_type == "resetClient":
                            raise InvalidEvent("Onics requested a fresh snapshot")
                        if "home" in event:
                            has_snapshot = True
                        state = self.data.apply(event)
                        if has_snapshot:
                            snapshot_timeout.reschedule(None)
                            if state != self.data or not self.last_update_success:
                                self.async_set_updated_data(state)
                            backoff = 1.0
                            if not self._ready.done():
                                self._ready.set_result(None)
                        if has_snapshot and isinstance(event.get("id"), str):
                            self._last_event_id = event["id"]
                raise OnicsError("Onics stream closed")
            except OnicsAuthError as err:
                self.async_set_update_error(
                    ConfigEntryAuthFailed("Onics authentication rejected")
                )
                if not self._ready.done():
                    self._ready.set_exception(err)
                else:
                    self.config_entry.async_start_reauth(self.hass)
                return
            except (OnicsError, InvalidEvent, TimeoutError) as err:
                self.async_set_update_error(
                    UpdateFailed(str(err) or "Timed out waiting for a home snapshot")
                )
                if isinstance(err, InvalidEvent):
                    self._last_event_id = None
                if isinstance(err, OnicsRateLimitError):
                    delay = max(delay, err.retry_after)
            delay = max(delay, self.client.retry_seconds)
            await asyncio.sleep(delay)
            backoff = min(max(backoff * 2, delay), 60.0)

    async def async_shutdown(self) -> None:
        """Cancel and await the stream, closing its HTTP response on every exit."""
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
