"""Exercise sign-in, home selection and reauthentication through Home Assistant."""

from unittest.mock import AsyncMock, patch
from uuid import UUID

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.loader import async_get_integration
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eva.api import EvaAuthError, EvaError, EvaRateLimitError
from custom_components.eva.const import DOMAIN

CREDENTIALS = {
    "username": "test@example.invalid",
    "password": "test-password",
}
LOGIN = {**CREDENTIALS, "advanced": {"environment": "test"}}
HOMES = [
    {"id": "test-home", "name": "Test home"},
    {"id": "other-home", "name": "Other home"},
]


@pytest.fixture
def mock_homes():
    with patch(
        "custom_components.eva.api.EvaClient.async_get_homes", return_value=HOMES
    ) as mocked:
        yield mocked


@pytest.fixture
def mock_setup():
    with patch("custom_components.eva.async_setup_entry", return_value=True) as mocked:
        yield mocked


async def test_user_form(hass):
    integration = await async_get_integration(hass, "eva")
    assert integration.name == "Eva"
    assert integration.has_branding
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    schema = result["data_schema"].schema
    assert list(schema) == ["username", "password", "advanced"]
    assert schema["advanced"].options == {"collapsed": True}
    assert result["data_schema"](CREDENTIALS)["advanced"]["environment"] == "prod"
    assert schema["advanced"].schema.schema["environment"].config["options"] == [
        {"value": "test", "label": "Test"},
        {"value": "qa", "label": "QA"},
        {"value": "prod", "label": "Prod"},
    ]
    assert schema["password"].config["type"] == "password"
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(
    "environment,expected_url",
    [
        (None, "https://home.api.evasmart.no"),
        ("test", "https://home-hla.smarthome-test.datek.io"),
        ("qa", "https://home-hla.smarthome-qa.datek.io"),
        ("prod", "https://home.api.evasmart.no"),
    ],
)
async def test_login_home_selection_and_private_session(
    hass, mock_setup, environment, expected_url
):
    sessions = []

    async def get_homes(client):
        assert client._base_url == expected_url
        assert client._headers["Authorization"] == aiohttp.encode_basic_auth(
            LOGIN["username"], LOGIN["password"]
        )
        assert "Authorization" not in client._session.headers
        assert client._headers["X-Client-Brand"] == "eva"
        assert client._headers["X-Schema-Version"] == "7"
        sessions.append(client._session)
        return HOMES

    login = dict(CREDENTIALS)
    if environment is not None:
        login["advanced"] = {"environment": environment}
    with patch(
        "custom_components.eva.api.EvaClient.async_get_homes",
        autospec=True,
        side_effect=get_homes,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], login
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "home"
    assert len(result["data_schema"].schema["home_id"].config["options"]) == 2
    assert sessions[0].closed
    assert hass.config_entries.async_entries(DOMAIN) == []
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"home_id": "test-home"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] | {"sse_client_id": None} == {
        **CREDENTIALS,
        "environment": environment or "prod",
        "home_id": "test-home",
        "sse_client_id": None,
    }
    assert UUID(result["data"]["sse_client_id"]).version == 4
    assert result["result"].unique_id == f"{environment or 'prod'}:test-home"
    mock_setup.assert_awaited_once()


@pytest.mark.parametrize(
    "error,reason",
    [
        (EvaAuthError("rejected"), "invalid_auth"),
        (EvaError("offline"), "cannot_connect"),
        (EvaRateLimitError(60), "rate_limited"),
    ],
)
async def test_login_failure_can_be_corrected(hass, mock_homes, error, reason, caplog):
    mock_homes.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=LOGIN
    )
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": reason}
    assert result["data_schema"](CREDENTIALS)["advanced"]["environment"] == "test"
    assert LOGIN["password"] not in caplog.text
    mock_homes.side_effect = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)
    assert result["step_id"] == "home"


async def test_no_homes(hass, mock_homes):
    mock_homes.return_value = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=LOGIN
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_homes"
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_invalid_environment_never_sends_credentials(hass, mock_homes):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={
            **LOGIN,
            "advanced": {"environment": "https://untrusted.example.invalid"},
        },
    )
    assert result["errors"] == {"base": "invalid_environment"}
    mock_homes.assert_not_awaited()


async def test_unknown_home_cannot_create_entry(hass, mock_homes):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=LOGIN
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {"home_id": "not-an-account-home"}
        )
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize(
    "environment,expected_type",
    [("test", FlowResultType.ABORT), ("prod", FlowResultType.CREATE_ENTRY)],
)
async def test_duplicate_home_is_scoped_to_environment(
    hass, mock_homes, mock_setup, environment, expected_type
):
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test:test-home",
        data={
            **CREDENTIALS,
            "environment": "test",
            "home_id": "test-home",
            "sse_client_id": "test-client",
        },
    )
    existing.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={**LOGIN, "advanced": {"environment": environment}},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"home_id": "test-home"}
    )
    await hass.async_block_till_done()
    assert result["type"] is expected_type
    if expected_type is FlowResultType.ABORT:
        assert result["reason"] == "already_configured"
    assert existing.data["password"] == LOGIN["password"]


@pytest.mark.parametrize(
    "outcome,reason",
    [
        (HOMES, "reauth_successful"),
        ([], "home_not_found"),
        (EvaAuthError("rejected"), "invalid_auth"),
        (EvaError("offline"), "cannot_connect"),
        (EvaRateLimitError(60), "rate_limited"),
    ],
)
async def test_reauth_preserves_account_home_and_stream_id(
    hass, mock_homes, outcome, reason
):
    data = {
        **CREDENTIALS,
        "environment": "test",
        "home_id": "test-home",
        "sse_client_id": "test-client",
    }
    entry = MockConfigEntry(domain=DOMAIN, unique_id="test:test-home", data=data)
    entry.add_to_hass(hass)
    if isinstance(outcome, Exception):
        mock_homes.side_effect = outcome
    else:
        mock_homes.return_value = outcome
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=data,
    )
    assert result["step_id"] == "reauth_confirm"
    assert list(result["data_schema"].schema) == ["password"]
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ) as reload_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"password": "new-test-password"}
        )
        await hass.async_block_till_done()
        if reason == "reauth_successful":
            assert result["type"] is FlowResultType.ABORT
            assert result["reason"] == reason
            assert dict(entry.data) == {**data, "password": "new-test-password"}
            reload_entry.assert_awaited_once_with(entry.entry_id)
        else:
            assert result["errors"] == {"base": reason}
            assert dict(entry.data) == data
            reload_entry.assert_not_awaited()
