"""Verify atomic shared-password updates and environment isolation."""

import asyncio
from copy import deepcopy
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.file import WriteError

from custom_components.eva.credentials import async_get_credentials


async def test_concurrent_saves_reload_and_failed_replacement(hass):
    credentials = await async_get_credentials(hass)
    await asyncio.gather(
        credentials.async_save("test", "a@example.invalid", "test-password"),
        credentials.async_save("prod", "a@example.invalid", "prod-password"),
        credentials.async_save("test", "b@example.invalid", "another-password"),
    )
    expected = deepcopy(credentials.accounts)
    assert expected == {
        "test": {
            "a@example.invalid": "test-password",
            "b@example.invalid": "another-password",
        },
        "prod": {"a@example.invalid": "prod-password"},
    }
    with patch(
        "homeassistant.helpers.storage.Store._async_write_data",
        side_effect=WriteError("disk full"),
    ):
        with pytest.raises(HomeAssistantError):
            await credentials.async_save("test", "a@example.invalid", "replacement")
    assert credentials.accounts == expected
    hass.data.pop("eva.credentials")
    assert (await async_get_credentials(hass)).accounts == expected


@pytest.mark.parametrize(
    "environment,username,password",
    [
        ("invalid", "a@example.invalid", "pw"),
        ("test", "", "pw"),
        ("test", "a@example.invalid", ""),
        ("test", "a:b", "pw"),
    ],
)
async def test_invalid_credentials_never_persist(
    hass, hass_storage, environment, username, password
):
    credentials = await async_get_credentials(hass)
    with pytest.raises(ValueError):
        await credentials.async_save(environment, username, password)
    assert not credentials.accounts
    assert "eva.credentials" not in hass_storage
