"""Set up the selected Onics home's authenticated SSE subscription."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import OnicsClient
from .const import CONF_ENVIRONMENT, ENVIRONMENTS
from .coordinator import OnicsConfigEntry, OnicsCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: OnicsConfigEntry) -> bool:
    """Wait for an authenticated snapshot before exposing any entities."""
    # HA detaches this private cookie session on failed setup, unload, or shutdown.
    client = OnicsClient(
        async_create_clientsession(hass),
        ENVIRONMENTS[entry.data[CONF_ENVIRONMENT]],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    entry.runtime_data = coordinator = OnicsCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnicsConfigEntry) -> bool:
    """Unload entities; entry cleanup cancels and awaits the SSE task."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
