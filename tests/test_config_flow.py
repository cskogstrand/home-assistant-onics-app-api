"""Exercise the implemented configuration gate through Home Assistant."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.onics.const import DOMAIN


async def test_user_flow_waits_for_confirmed_configuration(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "configuration_pending"
    assert hass.config_entries.async_entries(DOMAIN) == []
    assert not hass.states.async_entity_ids("sensor")
