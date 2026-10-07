"""Exercise saved login selection, password login and reuse through real HA flows."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import UUID

import aiohttp
import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.util.file import WriteError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eva.api import EvaAuthError, EvaError, EvaRateLimitError
from custom_components.eva.const import DOMAIN, ENVIRONMENT_NAMES, ENVIRONMENTS
from custom_components.eva.credentials import async_get_credentials

LOGIN = {"username": "test@example.invalid", "password": "test-password"}
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


async def start(hass, environment="prod"):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data={"environment": environment}
    )


async def choose(hass, result, data):
    return await hass.config_entries.flow.async_configure(result["flow_id"], data)


async def login(hass, environment="prod", credentials=None):
    result = await start(hass, environment)
    if result["type"] is FlowResultType.MENU:
        result = await choose(hass, result, {"next_step_id": "login"})
    assert result["step_id"] == "login"
    return await choose(hass, result, credentials or LOGIN)


async def test_environment_form_and_required_login_fields(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert list(result["data_schema"].schema) == ["environment"]
    assert result["data_schema"]({})["environment"] == "prod"
    result = await choose(hass, result, {"environment": "prod"})
    assert result["step_id"] == "login"
    assert list(result["data_schema"].schema) == ["username", "password"]
    assert result["data_schema"].schema["password"].config["type"] == "password"
    with pytest.raises(InvalidData):
        await choose(hass, result, {})


@pytest.mark.parametrize("environment", ENVIRONMENTS)
async def test_login_menu_translation_placeholders(hass, environment):
    credentials = await async_get_credentials(hass)
    await credentials.async_save(environment, LOGIN["username"], LOGIN["password"])
    result = await start(hass, environment)
    assert result["type"] is FlowResultType.MENU
    integration = Path(__file__).parents[1] / "custom_components" / DOMAIN
    for filename in ("strings.json", "translations/en.json"):
        step = json.loads((integration / filename).read_text())["config"]["step"][
            "login_method"
        ]
        # HA menu headers receive no placeholders; only descriptions do.
        assert step["title"].format() == "Log in to Eva"
        assert ENVIRONMENT_NAMES[environment] in step["description"].format(
            **result["description_placeholders"]
        )


@pytest.mark.parametrize("environment", ["prod", "test", "qa"])
async def test_login_saves_only_after_home_selection(
    hass, hass_storage, mock_setup, environment, caplog
):
    sessions = []

    async def get_homes(client):
        assert client._base_url == ENVIRONMENTS[environment]
        assert client._headers["Authorization"] == aiohttp.encode_basic_auth(
            LOGIN["username"], LOGIN["password"]
        )
        assert "Authorization" not in client._session.headers
        sessions.append(client._session)
        return HOMES

    with patch("custom_components.eva.api.EvaClient.async_get_homes", new=get_homes):
        result = await login(hass, environment)
    assert result["step_id"] == "home"
    assert sessions[0].closed
    assert "eva.credentials" not in hass_storage
    result = await choose(hass, result, {"home_id": "test-home"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].version == 4
    assert result["result"].unique_id == f"{environment}:test-home"
    assert UUID(result["data"]["sse_client_id"]).version == 4
    assert result["data"] | {"sse_client_id": None} == {
        "environment": environment,
        "username": LOGIN["username"],
        "home_id": "test-home",
        "sse_client_id": None,
    }
    assert hass_storage["eva.credentials"]["data"] == {
        environment: {LOGIN["username"]: LOGIN["password"]}
    }
    logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith(("homeassistant.", "custom_components.eva"))
    )
    assert LOGIN["password"] not in logs
    mock_setup.assert_awaited_once()


async def test_saved_login_picker_reuses_password_after_restart_and_isolates_environment(
    hass, mock_homes, mock_setup
):
    first = await choose(hass, await login(hass), {"home_id": "test-home"})
    await hass.async_block_till_done()
    hass.data.pop("eva.credentials")
    result = await start(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["account", "login"]
    result = await choose(hass, result, {"next_step_id": "account"})
    assert result["step_id"] == "account"
    assert result["data_schema"].schema["username"].config["options"] == [
        LOGIN["username"]
    ]

    async def get_homes(client):
        assert client._headers["Authorization"] == aiohttp.encode_basic_auth(
            LOGIN["username"], LOGIN["password"]
        )
        return HOMES

    with patch("custom_components.eva.api.EvaClient.async_get_homes", new=get_homes):
        result = await choose(hass, result, {"username": LOGIN["username"]})
    result = await choose(hass, result, {"home_id": "other-home"})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "password" not in result["data"]
    assert result["data"]["sse_client_id"] != first["data"]["sse_client_id"]
    other = await start(hass, "test")
    assert other["step_id"] == "login"


async def test_saved_list_and_new_user_button_never_prepopulate_passwords(hass):
    credentials = await async_get_credentials(hass)
    for environment, user in (
        ("test", "a@example.invalid"),
        ("test", "b@example.invalid"),
        ("prod", "c@example.invalid"),
    ):
        await credentials.async_save(environment, user, "private-password")
    result = await choose(hass, await start(hass, "test"), {"next_step_id": "account"})
    assert result["data_schema"].schema["username"].config["options"] == [
        "a@example.invalid",
        "b@example.invalid",
    ]
    with pytest.raises(InvalidData):
        await choose(hass, result, {"username": "c@example.invalid"})
    result = await choose(hass, await start(hass, "test"), {"next_step_id": "login"})
    assert result["step_id"] == "login"
    assert "private-password" not in str(result)
    assert result["data_schema"](LOGIN) == LOGIN


@pytest.mark.parametrize(
    "error,reason",
    [
        (EvaAuthError("rejected"), "invalid_auth"),
        (EvaRateLimitError(60), "rate_limited"),
        (EvaError("offline"), "cannot_connect"),
    ],
)
async def test_login_failure_can_be_corrected_without_saving(
    hass, hass_storage, mock_homes, error, reason
):
    mock_homes.side_effect = error
    result = await login(hass)
    assert result["step_id"] == "login"
    assert result["errors"] == {"base": reason}
    assert "eva.credentials" not in hass_storage
    mock_homes.side_effect = None
    result = await choose(hass, result, LOGIN)
    assert result["step_id"] == "home"


async def test_rejected_saved_login_opens_password_form_without_overwriting(
    hass, mock_homes
):
    credentials = await async_get_credentials(hass)
    await credentials.async_save("prod", LOGIN["username"], "old-password")
    mock_homes.side_effect = EvaAuthError("rejected")
    result = await choose(hass, await start(hass), {"next_step_id": "account"})
    result = await choose(hass, result, {"username": LOGIN["username"]})
    assert result["step_id"] == "login"
    assert result["errors"] == {"base": "invalid_auth"}
    assert (
        result["data_schema"]({"password": "replacement"})["username"]
        == LOGIN["username"]
    )
    assert credentials.accounts["prod"][LOGIN["username"]] == "old-password"
    assert "old-password" not in str(result)


async def test_blank_login_and_invalid_environment_never_send_credentials(
    hass, mock_homes
):
    result = await start(hass, "https://untrusted.example.invalid")
    assert result["errors"] == {"base": "invalid_environment"}
    result = await login(hass, credentials={"username": "", "password": ""})
    assert result["errors"] == {"base": "invalid_auth"}
    mock_homes.assert_not_awaited()


@pytest.mark.parametrize(
    "homes,reason", [([], "no_homes"), (HOMES, "already_configured")]
)
async def test_empty_account_or_duplicate_home_does_not_save(
    hass, hass_storage, mock_homes, homes, reason
):
    if homes:
        MockConfigEntry(
            domain=DOMAIN,
            version=4,
            unique_id="prod:test-home",
            data={"environment": "prod"},
        ).add_to_hass(hass)
    mock_homes.return_value = homes
    result = await login(hass)
    if homes:
        with pytest.raises(InvalidData):
            await choose(hass, result, {"home_id": "unknown"})
        result = await choose(hass, result, {"home_id": "test-home"})
    assert result["reason"] == reason
    assert "eva.credentials" not in hass_storage


async def test_failed_save_can_be_retried_without_creating_entry(
    hass, mock_homes, mock_setup
):
    result = await login(hass)
    with patch(
        "homeassistant.helpers.storage.Store._async_write_data",
        side_effect=WriteError("disk full"),
    ):
        result = await choose(hass, result, {"home_id": "test-home"})
    assert result["errors"] == {"base": "cannot_save"}
    assert not hass.config_entries.async_entries(DOMAIN)
    assert not (await async_get_credentials(hass)).accounts
    result = await choose(hass, result, {"home_id": "test-home"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()


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
async def test_reauth_preserves_identity_and_updates_only_matching_homes(
    hass, mock_homes, outcome, reason
):
    credentials = await async_get_credentials(hass)
    entries = []
    for environment, username, home in (
        ("test", LOGIN["username"], "test-home"),
        ("test", LOGIN["username"], "other-home"),
        ("prod", LOGIN["username"], "test-home"),
        ("test", "another@example.invalid", "test-home"),
    ):
        await credentials.async_save(environment, username, LOGIN["password"])
        entry = MockConfigEntry(
            domain=DOMAIN,
            version=4,
            unique_id=f"{environment}:{home}:{username}",
            data={
                "environment": environment,
                "username": username,
                "home_id": home,
                "sse_client_id": "stable-client",
            },
        )
        entry.add_to_hass(hass)
        entries.append(entry)
    original = [dict(entry.data) for entry in entries]
    saved = deepcopy(credentials.accounts)
    entry = entries[0]
    if isinstance(outcome, Exception):
        mock_homes.side_effect = outcome
    else:
        mock_homes.return_value = outcome
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    assert list(result["data_schema"].schema) == ["password"]
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ) as reload:
        result = await choose(hass, result, {"password": "new-password"})
        await hass.async_block_till_done()
    assert [dict(entry.data) for entry in entries] == original
    if reason == "reauth_successful":
        assert result["reason"] == reason
        assert credentials.accounts["test"][LOGIN["username"]] == "new-password"
        assert credentials.accounts["prod"] == saved["prod"]
        assert (
            credentials.accounts["test"]["another@example.invalid"] == LOGIN["password"]
        )
        assert {call.args[0] for call in reload.await_args_list} == {
            entries[0].entry_id,
            entries[1].entry_id,
        }
    else:
        assert result["errors"] == {"base": reason}
        assert credentials.accounts == saved
        reload.assert_not_awaited()


async def test_oauth_entry_without_recoverable_email_can_reauthenticate(
    hass, mock_homes
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        data={
            "environment": "test",
            "home_id": "test-home",
            "sse_client_id": "stable-client",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert list(result["data_schema"].schema) == ["username", "password"]
    with patch.object(
        hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
    ):
        result = await choose(hass, result, LOGIN)
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data["username"] == LOGIN["username"]
    assert entry.data["sse_client_id"] == "stable-client"
