"""Sign in to an Eva environment, select a home, and renew credentials."""

from typing import Any
from uuid import uuid4

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import EvaAuthError, EvaClient, EvaError, EvaRateLimitError
from .const import (
    CONF_ENVIRONMENT,
    CONF_HOME_ID,
    CONF_SSE_CLIENT_ID,
    DOMAIN,
    ENVIRONMENT_NAMES,
    ENVIRONMENTS,
)

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)


class EvaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one entry per environment and home, independent of account names."""

    VERSION = 1

    def __init__(self) -> None:
        """Keep uncommitted credentials only for the duration of this flow."""
        self._data: dict[str, Any] = {}
        self._homes: dict[str, str] = {}

    async def _async_get_homes(self, data: dict[str, Any]) -> dict[str, str]:
        """Validate credentials without retaining a session across UI steps."""
        session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            client = EvaClient(
                session,
                ENVIRONMENTS[data[CONF_ENVIRONMENT]],
                data[CONF_USERNAME],
                data[CONF_PASSWORD],
            )
            return {home["id"]: home["name"] for home in await client.async_get_homes()}
        finally:
            # The connector belongs to HA; detach instead of closing it.
            session.detach()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in to Prod unless an advanced environment is selected."""
        errors = {}
        environment = (
            (user_input or {}).get("advanced", {}).get(CONF_ENVIRONMENT, "prod")
        )
        if user_input is not None:
            if environment not in ENVIRONMENTS:
                errors["base"] = "invalid_environment"
            else:
                data = {
                    CONF_ENVIRONMENT: environment,
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                try:
                    homes = await self._async_get_homes(data)
                except EvaAuthError, ValueError:
                    errors["base"] = "invalid_auth"
                except EvaRateLimitError:
                    errors["base"] = "rate_limited"
                except EvaError:
                    errors["base"] = "cannot_connect"
                else:
                    if not homes:
                        return self.async_abort(reason="no_homes")
                    self._data = data
                    self._homes = homes
                    return await self.async_step_home()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_USERNAME, default=(user_input or {}).get(CONF_USERNAME, "")
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.EMAIL
                        )
                    ),
                    vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                    vol.Optional("advanced", default=dict): section(
                        vol.Schema(
                            {
                                vol.Required(
                                    CONF_ENVIRONMENT, default=environment
                                ): selector.SelectSelector(
                                    selector.SelectSelectorConfig(
                                        options=[
                                            {"value": key, "label": name}
                                            for key, name in ENVIRONMENT_NAMES.items()
                                        ],
                                        mode=selector.SelectSelectorMode.DROPDOWN,
                                    )
                                ),
                            }
                        ),
                        {"collapsed": True},
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_home(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select only a home returned for the authenticated account."""
        if not self._homes:
            return await self.async_step_user()
        errors = {}
        if user_input is not None:
            home_id = user_input.get(CONF_HOME_ID)
            if home_id not in self._homes:
                errors[CONF_HOME_ID] = "invalid_home"
            else:
                environment = self._data[CONF_ENVIRONMENT]
                await self.async_set_unique_id(f"{environment}:{home_id}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"{self._homes[home_id]} ({ENVIRONMENT_NAMES[environment]})",
                    data={
                        **self._data,
                        CONF_HOME_ID: home_id,
                        CONF_SSE_CLIENT_ID: str(uuid4()),
                    },
                )
        return self.async_show_form(
            step_id="home",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOME_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": key, "label": f"{name} ({key})"}
                                for key, name in self._homes.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Renew credentials for the same account, environment, and home."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate the new password and selected-home access before reloading."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            try:
                homes = await self._async_get_homes(
                    {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            except EvaAuthError, ValueError:
                errors["base"] = "invalid_auth"
            except EvaRateLimitError:
                errors["base"] = "rate_limited"
            except EvaError:
                errors["base"] = "cannot_connect"
            else:
                if entry.data[CONF_HOME_ID] not in homes:
                    errors["base"] = "home_not_found"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR}),
            description_placeholders={
                "username": entry.data[CONF_USERNAME],
                "environment": ENVIRONMENT_NAMES[entry.data[CONF_ENVIRONMENT]],
            },
            errors=errors,
        )
