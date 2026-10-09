"""Set up the selected Eva home's authenticated SSE subscription."""

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.storage import Store

from .api import EvaClient
from .const import CONF_ENVIRONMENT, DOMAIN, ENVIRONMENTS
from .coordinator import EvaConfigEntry, EvaCoordinator
from .credentials import async_get_credentials
from .services import async_setup_services

PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SCENE,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register home actions once; handlers resolve the currently loaded entry."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: EvaConfigEntry) -> bool:
    """Wait for an authenticated snapshot before exposing any entities."""
    credentials = await async_get_credentials(hass)
    environment = entry.data[CONF_ENVIRONMENT]
    username = entry.data.get(CONF_USERNAME)
    password = credentials.accounts.get(environment, {}).get(username)
    if not username or not password:
        raise ConfigEntryAuthFailed("Sign in to your Eva account")
    # HA detaches this private cookie session on failed setup, unload, or shutdown.
    client = EvaClient(
        async_create_clientsession(hass),
        ENVIRONMENTS[environment],
        username,
        password,
    )
    entry.runtime_data = coordinator = EvaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: EvaConfigEntry) -> bool:
    """Move legacy passwords to shared storage while preserving home identity."""
    if entry.version > 4:
        return False
    if entry.version < 4:
        data = dict(entry.data)
        environment = data[CONF_ENVIRONMENT]
        if not data.get(CONF_USERNAME) and data.get("account_id"):
            oauth = await Store(hass, 1, f"{DOMAIN}.oauth").async_load() or {}
            account = oauth.get(environment, {}).get(data["account_id"], {})
            if email := account.get("email"):
                data[CONF_USERNAME] = email
        if data.get(CONF_USERNAME) and data.get(CONF_PASSWORD):
            credentials = await async_get_credentials(hass)
            await credentials.async_save(
                environment,
                data[CONF_USERNAME],
                data[CONF_PASSWORD],
                replace=False,
            )
        for key in (
            CONF_PASSWORD,
            "account_id",
            "issuer",
            "auth_implementation",
            "token",
        ):
            data.pop(key, None)
        hass.config_entries.async_update_entry(entry, data=data, version=4)
        if all(
            entry.version == 4 for entry in hass.config_entries.async_entries(DOMAIN)
        ):
            await Store(hass, 1, f"{DOMAIN}.oauth").async_remove()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EvaConfigEntry) -> bool:
    """Unload entities; entry cleanup cancels and awaits the SSE task."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
