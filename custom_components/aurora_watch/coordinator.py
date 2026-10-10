"""One coordinator ticking every 60 s; each feed is fetched on its own interval.

A failed fetch keeps the last good data. The engine sees its age and refuses to say go
on stale data, so an SWPC outage shows up as `data_age` climbing, not as a false alert.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import sources
from .const import DOMAIN, INTERVALS, TICK, WIND_HISTORY
from .engine import Alert, HpSample, Inputs, KpSample, Result, Thresholds, WindSample, evaluate

_LOGGER = logging.getLogger(__name__)

# Used until satellite-longitudes.json is fetched (values as of 2026-10-10, degrees east).
DEFAULT_LONGITUDES = {19: -72.5, 18: -137.0}


class AuroraCoordinator(DataUpdateCoordinator[Result]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=TICK, config_entry=entry)
        self.thresholds = Thresholds()
        self._session = async_get_clientsession(hass)
        self._fetched: dict[str, datetime] = {}
        self._wind: dict[datetime, WindSample] = {}
        self._goes: dict[int, list[HpSample]] = {}
        self._longitudes: dict[int, float] = dict(DEFAULT_LONGITUDES)
        self._kp: list[KpSample] = []
        self._alerts: list[Alert] = []
        self._scales: tuple[int | None, int | None] = (None, None)
        self._last_go: datetime | None = None

    async def _get(self, path: str) -> Any:
        async with asyncio.timeout(30):
            resp = await self._session.get(sources.BASE + path)
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _due(self, feed: str, now: datetime) -> bool:
        last = self._fetched.get(feed)
        return last is None or now - last >= INTERVALS[feed] - TICK / 2

    async def _fetch(self, feed: str, now: datetime) -> None:
        if feed == "wind":
            # Seed 7 days once so the 120-min loading lookback works from the first tick.
            rows = await self._get(sources.WIND_1H if self._wind else sources.WIND_7D)
            for s in sources.parse_wind(rows):
                self._wind[s.observed] = s
            cutoff = now - WIND_HISTORY
            self._wind = {k: v for k, v in self._wind.items() if v.arrives >= cutoff}
        elif feed == "goes":
            primary, secondary = await asyncio.gather(self._get(sources.GOES_PRIMARY), self._get(sources.GOES_SECONDARY))
            goes = sources.parse_goes(primary)
            for sat, samples in sources.parse_goes(secondary).items():
                goes.setdefault(sat, []).extend(samples)
            self._goes = goes
        elif feed == "kp":
            self._kp = sources.parse_kp(await self._get(sources.KP_1M))
        elif feed == "alerts":
            self._alerts = sources.parse_alerts(await self._get(sources.ALERTS))
        elif feed == "scales":
            self._scales = sources.parse_scales(await self._get(sources.SCALES))
        elif feed == "longitudes":
            self._longitudes = sources.parse_longitudes(await self._get(sources.GOES_LONGITUDES)) or self._longitudes
        self._fetched[feed] = now

    async def _async_update_data(self) -> Result:
        now = dt_util.utcnow()
        due = [f for f in INTERVALS if self._due(f, now)]
        results = await asyncio.gather(*(self._fetch(f, now) for f in due), return_exceptions=True)
        for feed, res in zip(due, results):
            if isinstance(res, (aiohttp.ClientError, TimeoutError, ValueError)):
                _LOGGER.debug("SWPC %s fetch failed: %s", feed, res)
            elif isinstance(res, BaseException):
                raise res
        if not self._wind and "wind" not in self._fetched:
            raise UpdateFailed("No solar wind data from SWPC yet")

        sun = self.hass.states.get("sun.sun")
        try:
            elevation = float(sun.attributes["elevation"]) if sun else None
        except (KeyError, TypeError, ValueError):
            elevation = None

        g_now, g_forecast = self._scales
        result = evaluate(
            Inputs(
                now=now,
                wind=sorted(self._wind.values(), key=lambda s: s.arrives),
                goes=self._goes,
                goes_longitude=self._longitudes,
                kp=self._kp,
                alerts=self._alerts,
                g_now=g_now,
                g_forecast=g_forecast,
                sun_elevation=elevation,
                last_go=self._last_go,
            ),
            self.thresholds,
        )
        self._last_go = result.last_go
        return result
