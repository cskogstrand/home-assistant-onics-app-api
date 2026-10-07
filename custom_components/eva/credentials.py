"""Share saved Eva logins across homes in the same environment."""

import asyncio

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.singleton import singleton
from homeassistant.helpers.storage import Store

from .const import DOMAIN, ENVIRONMENTS


class EvaCredentials:
    """Persist passwords once, outside individual home entries."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.store = Store[dict[str, dict[str, str]]](
            hass, 1, f"{DOMAIN}.credentials", private=True, atomic_writes=True
        )
        self.accounts: dict[str, dict[str, str]] = {}
        # ponytail: serialize rare login writes; per-account locks if volume grows.
        self._lock = asyncio.Lock()

    async def async_save(
        self, environment: str, username: str, password: str, *, replace: bool = True
    ) -> None:
        """Publish a login only after its password has been saved successfully."""
        if (
            environment not in ENVIRONMENTS
            or not isinstance(username, str)
            or not username.strip()
            or ":" in username
            or not isinstance(password, str)
            or not password
        ):
            raise ValueError("Invalid Eva credentials")
        async with self._lock:
            accounts = self.accounts.get(environment, {})
            if not replace and username in accounts:
                return
            updated = {
                **self.accounts,
                environment: {**accounts, username: password},
            }
            await self.store.async_save(updated)
            if await self.store.async_load() != updated:
                raise HomeAssistantError("Unable to save Eva credentials")
            self.accounts = updated


@singleton(f"{DOMAIN}.credentials")
async def async_get_credentials(hass: HomeAssistant) -> EvaCredentials:
    """Load saved logins once for config flows and running homes."""
    credentials = EvaCredentials(hass)
    credentials.accounts = await credentials.store.async_load() or {}
    return credentials
