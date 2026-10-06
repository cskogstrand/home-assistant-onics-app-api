"""Expose Onics in the UI while deployment authentication is unconfirmed."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class OnicsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Do not collect credentials or create a nonfunctional entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain what must be confirmed before authentication can be implemented."""
        return self.async_abort(reason="configuration_pending")

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Keep a clear UI result if a development entry requests reauthentication."""
        return self.async_abort(reason="configuration_pending")
