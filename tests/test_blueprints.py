"""The blueprints, run in Home Assistant: they load, and they push when they should."""

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

BLUEPRINTS = Path(__file__).resolve().parents[1] / "blueprints" / "automation" / "aurora_watch"
STATUS = "sensor.aurora_watch_status"


async def _automation(hass, name):
    dest = Path(hass.config.path("blueprints", "automation", "aurora_watch"))
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(BLUEPRINTS / f"{name}.yaml", dest / f"{name}.yaml")
    config = {"automation": [{"id": name, "alias": name, "use_blueprint": {"path": f"aurora_watch/{name}.yaml", "input": {}}}]}
    assert await async_setup_component(hass, "automation", config)
    await hass.async_block_till_done()
    assert hass.states.get(f"automation.{name}").state == "on"


def _status(hass, state, **attrs):
    base = {"watch": False, "watch_reason": None, "reasons": [], "go_started": None, "go_ended": None}
    hass.states.async_set(STATUS, state, base | attrs)


async def test_watch_pushes_once_on_the_rising_edge(hass):
    calls = async_mock_service(hass, "notify", "mobile_app_tonys_iphone")
    _status(hass, "quiet")
    await _automation(hass, "watch")
    _status(hass, "watch", watch=True, watch_reason="NOAA G2 forecast")
    await hass.async_block_till_done()
    _status(hass, "elevated", watch=True, watch_reason="NOAA G2 forecast")  # still watching: no repeat
    await hass.async_block_till_done()
    assert len(calls) == 1 and "NOAA G2 forecast" in calls[0].data["message"]


async def test_go_pushes_time_sensitive_then_clears(hass, freezer):
    calls = async_mock_service(hass, "notify", "mobile_app_tonys_iphone")
    for entity, value in (("bz", "-18.2"), ("minutes_south", "42"), ("solar_wind_speed", "805"), ("kp_estimated", "6.33")):
        hass.states.async_set(f"sensor.aurora_watch_{entity}", value)
    hass.states.async_set("weather.forecast_home", "cloudy", {"cloud_coverage": 80})
    _status(hass, "elevated")
    await _automation(hass, "go")

    start = dt_util.utcnow()
    _status(hass, "go", reasons=["strong driving"], go_started=start.isoformat())
    await hass.async_block_till_done()
    assert len(calls) == 1
    go = calls[0].data
    assert go["title"] == "Aurora: go outside now"
    assert "Bz -18.2 nT" in go["message"] and "805 km/s" in go["message"] and "80% cloud" in go["message"]
    assert go["data"]["push"]["interruption-level"] == "time-sensitive"

    ended = dt_util.utcnow()
    _status(hass, "quiet", go_started=start.isoformat(), go_ended=ended.isoformat())
    await hass.async_block_till_done()
    assert len(calls) == 1, "clear waits 10 min of quiet"
    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert len(calls) == 2 and calls[1].data["title"] == "Aurora - quiet again"

    # Back to go within the cooldown: silent.
    _status(hass, "go", go_started=dt_util.utcnow().isoformat(), go_ended=ended.isoformat())
    await hass.async_block_till_done()
    assert len(calls) == 2


async def test_incoming_pushes_once_when_getting_dark(hass, freezer):
    calls = async_mock_service(hass, "notify", "mobile_app_tonys_iphone")
    hass.states.async_set("binary_sensor.aurora_watch_loading_incoming", "off", {})
    _status(hass, "elevated", sun_elevation=-8.0)
    await _automation(hass, "incoming")
    soon = (dt_util.utcnow() + timedelta(minutes=25)).isoformat()
    hass.states.async_set("binary_sensor.aurora_watch_loading_incoming", "on",
                          {"arrives": soon, "reason": "south Bz arriving ~17:02 UTC"})
    await hass.async_block_till_done()
    assert len(calls) == 1 and calls[0].data["title"] == "Aurora: get ready"
    assert "25 min" in calls[0].data["message"] or "24 min" in calls[0].data["message"]

    # Daylight: no push.
    hass.states.async_set("binary_sensor.aurora_watch_loading_incoming", "off", {})
    _status(hass, "elevated", sun_elevation=20.0)
    freezer.tick(timedelta(hours=2))
    hass.states.async_set("binary_sensor.aurora_watch_loading_incoming", "on", {"arrives": soon, "reason": "x"})
    await hass.async_block_till_done()
    assert len(calls) == 1
