"""Personal Onics integration; authentication wiring awaits deployment details."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Reject manually injected entries until the authentication contract is known."""
    raise ConfigEntryError("Onics authentication configuration has not been confirmed")
