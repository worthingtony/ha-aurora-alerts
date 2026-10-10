"""The Home Assistant side: config flow, setup, entities, served from recorded SWPC data."""

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import load
from custom_components.aurora_watch import sources
from custom_components.aurora_watch.const import DOMAIN

FEEDS = {
    sources.WIND_7D: "propagated-solar-wind.json",
    sources.WIND_1H: "propagated-solar-wind.json",
    sources.GOES_PRIMARY: "goes-primary-mag-7-day.json",
    sources.GOES_SECONDARY: "goes-secondary-mag-7-day.json",
    sources.GOES_LONGITUDES: "satellite-longitudes.json",
    sources.KP_1M: "planetary_k_index_1m.json",
    sources.ALERTS: "alerts.json",
    sources.SCALES: "noaa-scales.json",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def swpc(aioclient_mock):
    for path, fixture in FEEDS.items():
        aioclient_mock.get(sources.BASE + path, json=load(fixture))
    return aioclient_mock


async def test_config_flow_is_single_instance(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("custom_components.aurora_watch.async_setup_entry", _ok)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert again["type"] is FlowResultType.ABORT and again["reason"] in ("already_configured", "single_instance_allowed")


async def _ok(*_):
    return True


async def test_storm_after_dark_is_go(hass, swpc, freezer):
    freezer.move_to("2026-10-10T17:35:00+00:00")
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": -20.0})
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    status = hass.states.get("sensor.aurora_watch_status")
    assert status.state == "go", status.attributes["reasons"]
    assert status.attributes["strong_driving"] and status.attributes["go_started"]
    assert status.attributes["go_ended"] is None
    assert float(hass.states.get("sensor.aurora_watch_bz").state) <= -10
    assert float(hass.states.get("sensor.aurora_watch_solar_wind_speed").state) >= 600
    assert float(hass.states.get("sensor.aurora_watch_data_age").state) <= 10
    assert hass.states.get("binary_sensor.aurora_watch_dark_enough").state == "on"
    assert hass.states.get("sensor.aurora_watch_g_scale_now").state == "2"
    assert "message" in hass.states.get("sensor.aurora_watch_swpc_alert").attributes
    assert hass.states.get("sensor.aurora_watch_swpc_alert").state.startswith("ALERT: Geomagnetic K-index of 6")
    # The 7-day seed is fetched once; later ticks use the 7 KB file.
    assert any(str(call[1]).endswith(sources.WIND_7D) for call in swpc.mock_calls)


async def test_kp_trigger_is_tunable_from_the_ui(hass, swpc, freezer):
    freezer.move_to("2026-10-10T17:35:00+00:00")
    hass.states.async_set("sun.sun", "below_horizon", {"elevation": -20.0})
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.aurora_watch_kp_trigger").state == "5.0"
    assert hass.states.get("sensor.aurora_watch_status").state == "go"

    await hass.services.async_call("number", "set_value", {"entity_id": "number.aurora_watch_kp_trigger", "value": 8}, blocking=True)
    await hass.async_block_till_done()
    status = hass.states.get("sensor.aurora_watch_status")
    assert status.attributes["kp_trigger"] == 8
    # Kp ~6 now, under the new trigger: still loaded, no longer go. The latch holds go
    # only while Kp reaches, so it drops too.
    assert status.state == "elevated"


async def test_daylight_is_not_go(hass, swpc, freezer):
    freezer.move_to("2026-10-10T17:35:00+00:00")
    hass.states.async_set("sun.sun", "above_horizon", {"elevation": 35.0})
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.aurora_watch_status").state == "elevated"
    assert hass.states.get("binary_sensor.aurora_watch_dark_enough").state == "off"


async def test_swpc_down_at_startup_retries(hass, aioclient_mock):
    aioclient_mock.get(sources.BASE + sources.WIND_7D, status=503)
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY
