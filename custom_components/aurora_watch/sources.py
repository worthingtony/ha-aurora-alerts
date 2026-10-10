"""SWPC feeds: URLs and parsers. Parsers take decoded JSON and never raise on a bad row.

All feeds verified live 2026-10-10. The handoff's `products/solar-wind/*.json` files are
gone (404); SWPC retired them in 2026.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .engine import GLENDALE_LEVELS, Alert, GlendaleAlert, HpSample, KpSample, WindSample

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
ALERTS_PAGE = "https://www.swpc.noaa.gov/products/alerts-watches-and-warnings"
SCALES = "/products/noaa-scales.json"


GLENDALE_URL = "https://t.me/s/GlendaleApp"


def parse_glendale(page: str, now: datetime | None = None) -> list[GlendaleAlert]:
    """The Glendale App's public Telegram preview. Its posts are plain sentences:
    'ORANGE ALERT : Moderate geomagnetic substorm in progress. ...' and
    'INTERPLANETARY SHOCK detected that will hit Earth at ~15:31 UTC ...'."""
    out = []
    blocks = re.split(r'<div class="tgme_widget_message_wrap', page)[1:]
    for block in blocks:
        text_m = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        time_m = re.search(r'<time datetime="([^"]+)"', block)
        post_m = re.search(r'data-post="([^"]+)"', block)
        url = f"https://t.me/{post_m.group(1)}" if post_m else None
        if not (text_m and time_m):
            continue
        try:
            posted = datetime.fromisoformat(time_m.group(1)).astimezone(timezone.utc)
        except ValueError:
            continue
        text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", text_m.group(1)))).strip()
        first = text.splitlines()[0].strip() if text else ""
        level_m = re.match(r"([A-Z]+) ALERT\s*:\s*(.*?substorm in progress)", first)
        if level_m and level_m.group(1) in GLENDALE_LEVELS:
            out.append(GlendaleAlert(posted, GLENDALE_LEVELS[level_m.group(1)], f"{level_m.group(1).title()} alert - {level_m.group(2)}", url=url))
            continue
        eta_m = re.search(r"(SHOCK|IMF ENHANCEMENT).*?hit Earth at ~(\d{1,2}):(\d{2}) UTC", first)
        if eta_m:
            arrives = posted.replace(hour=int(eta_m.group(2)), minute=int(eta_m.group(3)), second=0, microsecond=0)
            if arrives < posted - timedelta(hours=1):  # past midnight UTC
                arrives += timedelta(days=1)
            kind = "Interplanetary shock" if eta_m.group(1) == "SHOCK" else "IMF enhancement"
            out.append(GlendaleAlert(posted, 0, f"{kind} arriving ~{arrives:%H:%M} UTC", arrives, url))
    return sorted(out, key=lambda g: g.posted)


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
