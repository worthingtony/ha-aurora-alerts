"""SWPC feeds: URLs and parsers. Parsers take decoded JSON and never raise on a bad row.

All feeds verified live 2026-10-10. The handoff's `products/solar-wind/*.json` files are
gone (404); SWPC retired them in 2026.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .engine import Alert, HpSample, KpSample, WindSample

BASE = "https://services.swpc.noaa.gov"
# 1-min L1 wind and IMF, time-shifted to Earth arrival. The 1-hour file is 7 KB; the
# 7-day file (1.2 MB) seeds history once at startup.
WIND_1H = "/products/geospace/propagated-solar-wind-1-hour.json"
WIND_7D = "/products/geospace/propagated-solar-wind.json"
GOES_PRIMARY = "/json/goes/primary/magnetometers-6-hour.json"
GOES_SECONDARY = "/json/goes/secondary/magnetometers-6-hour.json"
GOES_LONGITUDES = "/json/goes/satellite-longitudes.json"
KP_1M = "/json/planetary_k_index_1m.json"
ALERTS = "/products/alerts.json"
SCALES = "/products/noaa-scales.json"


def parse_time(value: Any) -> datetime | None:
    """SWPC writes UTC as '2026-10-10T17:13:01Z', '2026-10-10T17:44:00' or '2026-10-10 17:18:13.507'."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "").replace(" ", "T"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def parse_wind(rows: Any) -> list[WindSample]:
    """Array of arrays; row 0 is the header. Parse by name, not index."""
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    col = {name: i for i, name in enumerate(rows[0])}
    out = []
    for row in rows[1:]:
        try:
            observed = parse_time(row[col["time_tag"]])
            arrives = parse_time(row[col["propagated_time_tag"]])
            values = {k: _float(row[col[k]]) for k in ("bz", "bt", "speed", "density")}
        except (KeyError, IndexError, TypeError):
            continue
        if observed and arrives:
            out.append(WindSample(observed, arrives, **values))
    return sorted(out, key=lambda s: s.arrives)


def parse_goes(rows: Any) -> dict[int, list[HpSample]]:
    out: dict[int, list[HpSample]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        t = parse_time(row.get("time_tag"))
        sat = row.get("satellite")
        if t and isinstance(sat, int):
            out.setdefault(sat, []).append(HpSample(t, _float(row.get("Hp"))))
    for samples in out.values():
        samples.sort(key=lambda s: s.time)
    return out


def parse_longitudes(rows: Any) -> dict[int, float]:
    """SWPC gives degrees west as positive numbers; return degrees east."""
    out = {}
    for row in rows if isinstance(rows, list) else []:
        lon = _float(row.get("longitude")) if isinstance(row, dict) else None
        if lon is not None and isinstance(row.get("satellite"), int):
            out[row["satellite"]] = -lon
    return out


def parse_kp(rows: Any) -> list[KpSample]:
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        t = parse_time(row.get("time_tag"))
        kp = _float(row.get("estimated_kp"))
        if t and kp is not None:
            out.append(KpSample(t, kp))
    return sorted(out, key=lambda k: k.time)


def parse_alerts(rows: Any) -> list[Alert]:
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        t = parse_time(row.get("issue_datetime"))
        if t:
            out.append(Alert(t, str(row.get("product_id", "")), str(row.get("message", "")).replace("\r\n", "\n")))
    return out


def parse_scales(obj: Any) -> tuple[int | None, int | None]:
    """(G now, max G forecast for today and tomorrow UTC). Keys: '0' now, '1'-'3' forecast days."""
    def g(key: str) -> int | None:
        try:
            return int(obj[key]["G"]["Scale"])
        except (KeyError, TypeError, ValueError):
            return None

    forecast = [v for v in (g("1"), g("2")) if v is not None]
    return g("0"), max(forecast) if forecast else None
