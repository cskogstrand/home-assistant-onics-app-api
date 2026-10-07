"""Choose an environment, reuse a saved login, and select an Eva home."""

from typing import Any
from uuid import uuid4

import probatio as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.exceptions import HomeAssistantError
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
from .credentials import async_get_credentials

PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)
EMAIL_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
)


class EvaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Keep home identities stable and share logins per environment."""

    VERSION = 4

    def __init__(self) -> None:
        self._environment = "prod"
        self._username = ""
        self._password = ""
        self._saved_account = False
        self._homes: dict[str, str] = {}

    async def _async_validate_login(self, username: str, password: str) -> str | None:
        """Check credentials without retaining a session across UI steps."""
        session = async_create_clientsession(self.hass, auto_cleanup=False)
        try:
            client = EvaClient(
                session, ENVIRONMENTS[self._environment], username, password
            )
            self._homes = {
                home["id"]: home["name"] for home in await client.async_get_homes()
            }
        except EvaAuthError, ValueError:
            return "invalid_auth"
        except EvaRateLimitError:
            return "rate_limited"
        except EvaError:
            return "cannot_connect"
        finally:
            # The connector belongs to HA; detach instead of closing it.
            session.detach()
        return None

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Select the environment before showing any saved logins."""
        errors = {}
        if user_input is not None:
            environment = user_input[CONF_ENVIRONMENT]
            if environment not in ENVIRONMENTS:
                errors["base"] = "invalid_environment"
            else:
                self._environment = environment
                credentials = await async_get_credentials(self.hass)
                if credentials.accounts.get(environment):
                    return await self.async_step_login_method()
                return await self.async_step_login()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENVIRONMENT, default=self._environment
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": key, "label": name}
                                for key, name in ENVIRONMENT_NAMES.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_login_method(self, user_input=None) -> ConfigFlowResult:
        """Offer explicit saved-login and new-login buttons."""
        return self.async_show_menu(
            step_id="login_method",
            menu_options=["account", "login"],
            description_placeholders={
                "environment": ENVIRONMENT_NAMES[self._environment]
            },
        )

    async def async_step_account(self, user_input=None) -> ConfigFlowResult:
        """Always let the user select a saved login, even if there is only one."""
        credentials = await async_get_credentials(self.hass)
        accounts = credentials.accounts.get(self._environment, {})
        if not accounts:
            return await self.async_step_login()
        errors = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME]
            if username not in accounts:
                errors["base"] = "invalid_account"
            else:
                self._username = username
                error = await self._async_validate_login(username, accounts[username])
                if error == "invalid_auth":
                    return await self.async_step_login(errors={"base": "invalid_auth"})
                if error:
                    errors["base"] = error
                else:
                    self._saved_account = True
                    return await self.async_step_home()
        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=sorted(accounts),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            description_placeholders={
                "environment": ENVIRONMENT_NAMES[self._environment]
            },
            errors=errors,
        )

    async def async_step_login(
        self, user_input=None, *, errors=None
    ) -> ConfigFlowResult:
        """Ask for real credentials; never submit a blank or placeholder password."""
        errors = errors or {}
        if user_input is not None:
            self._username = user_input[CONF_USERNAME].strip()
            self._password = user_input[CONF_PASSWORD]
            error = await self._async_validate_login(self._username, self._password)
            if error:
                errors["base"] = error
            else:
                self._saved_account = False
                return await self.async_step_home()
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=self._username): EMAIL_SELECTOR,
                    vol.Required(CONF_PASSWORD): PASSWORD_SELECTOR,
                }
            ),
            description_placeholders={
                "environment": ENVIRONMENT_NAMES[self._environment]
            },
            errors=errors,
        )

    async def _async_save_login(self) -> None:
        """Update the shared password and reload only homes using this login."""
        credentials = await async_get_credentials(self.hass)
        await credentials.async_save(self._environment, self._username, self._password)
        for entry in self._async_current_entries():
            if (
                entry.data.get(CONF_ENVIRONMENT) == self._environment
                and entry.data.get(CONF_USERNAME) == self._username
                and entry.entry_id != self.context.get("entry_id")
            ):
                self.hass.config_entries.async_schedule_reload(entry.entry_id)

    async def async_step_home(self, user_input=None) -> ConfigFlowResult:
        """Save new credentials only when a valid, unconfigured home is selected."""
        if not self._homes:
            return self.async_abort(reason="no_homes")
        errors = {}
        if user_input is not None:
            home_id = user_input[CONF_HOME_ID]
            if home_id not in self._homes:
                errors[CONF_HOME_ID] = "invalid_home"
            else:
                await self.async_set_unique_id(f"{self._environment}:{home_id}")
                self._abort_if_unique_id_configured()
                try:
                    if not self._saved_account:
                        await self._async_save_login()
                except HomeAssistantError:
                    errors["base"] = "cannot_save"
                else:
                    return self.async_create_entry(
                        title=f"{self._homes[home_id]} ({ENVIRONMENT_NAMES[self._environment]})",
                        data={
                            CONF_ENVIRONMENT: self._environment,
                            CONF_USERNAME: self._username,
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
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        self._environment = entry_data[CONF_ENVIRONMENT]
        self._username = entry_data.get(CONF_USERNAME, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        """Check the new password and existing-home access before replacing it."""
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            self._username = (
                entry.data.get(CONF_USERNAME) or user_input[CONF_USERNAME].strip()
            )
            self._password = user_input[CONF_PASSWORD]
            error = await self._async_validate_login(self._username, self._password)
            if error:
                errors["base"] = error
            elif entry.data[CONF_HOME_ID] not in self._homes:
                errors["base"] = "home_not_found"
            else:
                try:
                    await self._async_save_login()
                except HomeAssistantError:
                    errors["base"] = "cannot_save"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data={
                            **{
                                key: value
                                for key, value in entry.data.items()
                                if key != CONF_PASSWORD
                            },
                            CONF_USERNAME: self._username,
                        },
                    )
        schema = {}
        if not entry.data.get(CONF_USERNAME):
            schema[vol.Required(CONF_USERNAME, default=self._username)] = EMAIL_SELECTOR
        schema[vol.Required(CONF_PASSWORD)] = PASSWORD_SELECTOR
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "username": self._username,
                "environment": ENVIRONMENT_NAMES[self._environment],
            },
            errors=errors,
        )
