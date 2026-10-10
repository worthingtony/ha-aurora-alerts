"""Constants. The substorm thresholds live in engine.Thresholds, in one place."""

from datetime import timedelta

DOMAIN = "aurora_watch"
NAME = "Aurora Watch"
ATTRIBUTION = "Data: NOAA Space Weather Prediction Center"

TICK = timedelta(seconds=60)
# How often each feed is fetched. The tick is 60 s; slower feeds skip ticks.
INTERVALS = {
    "wind": timedelta(seconds=60),
    "goes": timedelta(seconds=60),
    "kp": timedelta(minutes=3),
    "alerts": timedelta(minutes=15),
    "scales": timedelta(minutes=15),
    "longitudes": timedelta(hours=24),
    "glendale": timedelta(minutes=2),
}
HOME_ZONE = "zone.home"
# Keep this much solar wind history in memory: the onset gate looks back 120 min.
WIND_HISTORY = timedelta(hours=4)
