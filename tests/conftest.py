"""Load the engine and parsers without importing Home Assistant.

The integration package's __init__ imports homeassistant; the logic modules don't. A stub
package lets `from .engine import ...` resolve without running that __init__.
"""

import gzip
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "custom_components" / "aurora_watch"
FIXTURES = Path(__file__).parent / "fixtures"

stub = types.ModuleType("aurora_watch")
stub.__path__ = [str(PKG)]
sys.modules.setdefault("aurora_watch", stub)

from aurora_watch import engine, sources  # noqa: E402


def load(name: str):
    with gzip.open(FIXTURES / f"{name}.gz", "rt") as f:
        return json.load(f)


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


class Replay:
    """What the coordinator would have seen at `now`, from the recorded 2026-10-03..10 data.

    Kp: the 1-min estimated feed only covers the last 6 h before capture, so earlier
    times fall back to the official 3-hourly Kp, spread across its interval.
    """

    LATENCY = timedelta(minutes=2)

    def __init__(self):
        self.wind = sources.parse_wind(load("propagated-solar-wind.json"))
        self.goes = {}
        for f in ("goes-primary-mag-7-day.json", "goes-secondary-mag-7-day.json"):
            for sat, samples in sources.parse_goes(load(f)).items():
                self.goes.setdefault(sat, []).extend(samples)
        self.longitudes = sources.parse_longitudes(load("satellite-longitudes.json"))
        kp1m = sources.parse_kp(load("planetary_k_index_1m.json"))
        three_hourly = []
        for row in load("noaa-planetary-k-index.json"):
            start = sources.parse_time(row["time_tag"])
            three_hourly += [engine.KpSample(start + timedelta(minutes=m), float(row["Kp"])) for m in range(0, 180, 5)]
        first_1m = kp1m[0].time if kp1m else None
        self.kp = sorted([k for k in three_hourly if first_1m is None or k.time < first_1m] + kp1m, key=lambda k: k.time)
        self.alerts = sources.parse_alerts(load("alerts.json"))

    def inputs(self, now: datetime, sun_elevation: float = -20.0, last_go=None, **kw) -> engine.Inputs:
        seen = now - self.LATENCY
        return engine.Inputs(
            now=now,
            wind=[s for s in self.wind if s.observed <= seen],
            goes={sat: [s for s in v if s.time <= seen and s.time > now - timedelta(hours=6)] for sat, v in self.goes.items()},
            goes_longitude=self.longitudes,
            kp=[k for k in self.kp if k.time <= seen],
            alerts=[a for a in self.alerts if a.issued <= now],
            g_now=kw.get("g_now"),
            g_forecast=kw.get("g_forecast"),
            sun_elevation=sun_elevation,
            last_go=last_go,
        )


@pytest.fixture(scope="session")
def replay() -> Replay:
    return Replay()
