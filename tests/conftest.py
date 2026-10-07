"""Entirely invented local fixtures; never contact an Eva deployment."""

import pytest

from custom_components.eva.credentials import async_get_credentials


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Allow the real Home Assistant loader to discover Eva."""


@pytest.fixture
def snapshot():
    """Minimal documented home structure containing no private device data."""
    return {
        "eventType": "initialHome",
        "id": "test-event-1",
        "home": {
            "id": "test-home",
            "name": "Test home",
            "gateway": {"online": True},
            "rooms": [
                {
                    "id": "test-room",
                    "name": "Test room",
                    "devices": [
                        {
                            "id": "test-device",
                            "name": "Test thermometer",
                            "online": True,
                            "vendor": "Test vendor",
                            "model": "Test model",
                            "attributes": [
                                {
                                    "name": "temperature",
                                    "value": 21.5,
                                    "updatedAt": "2026-01-01T00:00:00Z",
                                    "minValue": -20,
                                    "maxValue": 60,
                                    "options": [20, 21.5],
                                    "preview": "test",
                                }
                            ],
                        }
                    ],
                }
            ],
        },
    }


@pytest.fixture
async def saved_credentials(hass):
    credentials = await async_get_credentials(hass)
    for environment in ("test", "prod"):
        await credentials.async_save(
            environment, "test@example.invalid", "test-password"
        )
    return credentials
