"""Substorm logic: inputs in, status out. No Home Assistant imports, so it tests alone.

The method is Vince Ledvina's: south Bz loads the magnetosphere, a GOES Hp spike marks
the release (onset), and Kp only says whether the oval reaches 53 deg geomagnetic.
See ARCHITECTURE.md for why each threshold is what it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import mean, median

QUIET = "quiet"
WATCH = "watch"
ELEVATED = "elevated"
GO = "go"
STATUSES = [QUIET, WATCH, ELEVATED, GO]


@dataclass(frozen=True)
class Thresholds:
    """Every tunable number, in one place. Tune after real events, not before."""

    # Loading: Bz south of this for most of the window.
    bz_south: float = -10.0
    south_window_min: int = 30
    south_fraction: float = 0.8
    # An onset only counts if the magnetosphere was loaded recently.
    loaded_lookback_min: int = 120
    loaded_minutes: int = 30
    # Storm-time driving strong enough to light the sky without a clean substorm.
    strong_bz_mean: float = -15.0
    strong_speed: float = 600.0
    # Shock arrival: density jumps against the prior hour.
    shock_density_ratio: float = 2.0
    # Reach: at 53 deg geomagnetic the oval has to be pushed south.
    kp_reach: float = 5.0
    # Max over this window: SWPC's 1-min estimate restarts near 0 at each 3-hour Kp
    # boundary (seen 2026-10-10 18:00 UTC: 7.0 then 0.0), so the latest row alone lies.
    kp_window_min: float = 30.0
    # GOES onset: a sharp rise after a decline (dipolarization after tail stretching).
    onset_rise_nt: float = 15.0
    onset_rise_window_min: int = 10
    onset_decline_nt: float = 20.0
    onset_decline_window_min: int = 120
    goes_max_age_min: float = 10.0
    # Dipolarizations show near local midnight; dayside jumps are magnetopause crossings.
    goes_night_start_lt: float = 20.0
    goes_night_end_lt: float = 4.0
    # Hp < 0 or a step this big per minute is the satellite outside the magnetosphere.
    hp_max_step_per_min: float = 50.0
    # Never say go on stale data.
    max_data_age_min: float = 10.0
    sun_dark_elevation: float = -12.0
    # Expansion phase: hold go this long after a trigger.
    go_latch_min: int = 30
    # NOAA context for watch.
    watch_g_scale: int = 2
    alert_lookback_h: float = 6.0


@dataclass(frozen=True)
class WindSample:
    observed: datetime  # at L1
    arrives: datetime  # SWPC's propagated time at Earth
    bz: float | None
    bt: float | None
    speed: float | None
    density: float | None


@dataclass(frozen=True)
class HpSample:
    time: datetime
    hp: float | None


@dataclass(frozen=True)
class KpSample:
    time: datetime
    kp: float


@dataclass(frozen=True)
class Alert:
    issued: datetime
    product_id: str
    message: str

    @property
    def headline(self) -> str:
        prefixes = ("ALERT", "WARNING", "WATCH", "SUMMARY", "EXTENDED WARNING", "CANCEL")
        for line in self.message.splitlines():
            if line.strip().startswith(prefixes):
                return line.strip()
        return self.product_id

    @property
    def geomagnetic(self) -> bool:
        return "Geomagnetic" in self.message


@dataclass
class Inputs:
    now: datetime
    wind: list[WindSample]  # ascending by arrives
    goes: dict[int, list[HpSample]]  # by satellite number, ascending
    goes_longitude: dict[int, float]  # degrees east (west is negative)
    kp: list[KpSample]  # ascending
    alerts: list[Alert]
    g_now: int | None = None
    g_forecast: int | None = None  # max G for today and tomorrow (UTC), i.e. tonight
    sun_elevation: float | None = None
    last_go: datetime | None = None  # when go last triggered, for the latch


@dataclass
class Result:
    status: str = QUIET
    reasons: list[str] = field(default_factory=list)
    bz: float | None = None
    bt: float | None = None
    speed: float | None = None
    density: float | None = None
    bz_south_fraction: float | None = None
    bz_mean_30: float | None = None
    minutes_south: int = 0
    loaded: bool = False
    shock: bool = False
    strong: bool = False
    goes_satellite: int | None = None
    hp: float | None = None
    hp_rise: float | None = None
    onset: bool = False
    kp: float | None = None
    dark: bool | None = None
    data_age_min: float | None = None
    fresh: bool = False
    watch: bool = False
    watch_reason: str | None = None
    g_now: int | None = None
    g_forecast: int | None = None
    alert: Alert | None = None
    go_triggered: bool = False  # a fresh trigger this tick, not the latch holding
    last_go: datetime | None = None


def _minutes(delta: timedelta) -> float:
    return delta.total_seconds() / 60


def _between(wind: list[WindSample], start: datetime, end: datetime) -> list[WindSample]:
    return [s for s in wind if start < s.arrives <= end]


def local_time_hours(now: datetime, longitude_east: float) -> float:
    return (now.hour + now.minute / 60 + longitude_east / 15) % 24


def pick_goes(inputs: Inputs, t: Thresholds) -> int | None:
    """The satellite nearest local midnight, if any is on the night side."""
    best: tuple[float, int] | None = None
    for sat, lon in inputs.goes_longitude.items():
        if sat not in inputs.goes:
            continue
        lt = local_time_hours(inputs.now, lon)
        if not (lt >= t.goes_night_start_lt or lt < t.goes_night_end_lt):
            continue
        from_midnight = min(lt, 24 - lt)
        if best is None or from_midnight < best[0]:
            best = (from_midnight, sat)
    return best[1] if best else None


def clean_hp(samples: list[HpSample], t: Thresholds) -> list[HpSample]:
    """Drop magnetopause crossings: negative Hp, and implausible jumps."""
    kept: list[HpSample] = []
    for s in samples:
        if s.hp is None or s.hp < 0:
            continue
        if kept:
            dt = max(_minutes(s.time - kept[-1].time), 1.0)
            if abs(s.hp - kept[-1].hp) / dt > t.hp_max_step_per_min:
                continue
        kept.append(s)
    return kept


def goes_onset(samples: list[HpSample], now: datetime, t: Thresholds) -> tuple[bool, float | None, float | None, str | None]:
    """(onset, latest Hp, rise, why not). Rise over 10 min after a decline over 120 min."""
    window = [s for s in samples if now - timedelta(minutes=t.onset_decline_window_min + t.onset_rise_window_min) < s.time <= now]
    clean = clean_hp(window, t)
    if not clean:
        return False, None, None, "no usable GOES Hp"
    latest = clean[-1]
    if _minutes(now - latest.time) > t.goes_max_age_min:
        return False, latest.hp, None, "GOES data stale"
    recent = [s.hp for s in clean if s.time > now - timedelta(minutes=t.onset_rise_window_min)]
    before = [s.hp for s in clean if s.time <= now - timedelta(minutes=t.onset_rise_window_min)]
    if len(recent) < 3 or len(before) < 30:
        return False, latest.hp, None, "not enough GOES history"
    rise = latest.hp - min(recent)
    decline = max(before) - min(recent)
    return rise >= t.onset_rise_nt and decline >= t.onset_decline_nt, latest.hp, rise, None


def watch_active(inputs: Inputs, t: Thresholds) -> tuple[bool, str | None]:
    for label, g in (("now", inputs.g_now), ("forecast", inputs.g_forecast)):
        if g is not None and g >= t.watch_g_scale:
            return True, f"NOAA G{g} {label}"
    since = inputs.now - timedelta(hours=t.alert_lookback_h)
    for a in sorted(inputs.alerts, key=lambda a: a.issued, reverse=True):
        if a.issued < since:
            break
        h = a.headline
        if "Sudden Impulse" in h:
            return True, h
        if "K-index of" in h:
            try:
                k = int(h.split("K-index of", 1)[1].split()[0])
            except (ValueError, IndexError):
                continue
            if k >= 4 + t.watch_g_scale:  # G2 is K6
                return True, h
    return False, None


def evaluate(inputs: Inputs, t: Thresholds = Thresholds()) -> Result:
    now = inputs.now
    r = Result()
    why: list[str] = []

    # --- Solar wind, as it arrives at Earth ---
    arrived = [s for s in inputs.wind if s.arrives <= now]
    if inputs.wind:
        r.data_age_min = round(_minutes(now - max(s.observed for s in inputs.wind)), 1)
    r.fresh = r.data_age_min is not None and r.data_age_min <= t.max_data_age_min
    if not r.fresh:
        why.append("solar wind data stale or missing" if r.data_age_min is None else f"solar wind data {r.data_age_min:.0f} min old")

    for name in ("bz", "bt", "speed", "density"):
        latest = next((getattr(s, name) for s in reversed(arrived) if getattr(s, name) is not None), None)
        setattr(r, name, latest)

    win = [s for s in _between(arrived, now - timedelta(minutes=t.south_window_min), now) if s.bz is not None]
    if len(win) >= t.south_window_min / 2:
        r.bz_south_fraction = sum(s.bz <= t.bz_south for s in win) / len(win)
        r.bz_mean_30 = mean(s.bz for s in win)
        speeds = [s.speed for s in win if s.speed is not None]
        r.loaded = r.bz_south_fraction >= t.south_fraction
        r.strong = r.bz_mean_30 <= t.strong_bz_mean and bool(speeds) and mean(speeds) >= t.strong_speed

    with_bz = [s for s in arrived if s.bz is not None]
    if with_bz and with_bz[-1].bz <= t.bz_south:
        start = with_bz[-1]
        for s in reversed(with_bz):
            if s.bz > t.bz_south:
                break
            start = s
        r.minutes_south = int(_minutes(with_bz[-1].arrives - start.arrives)) + 1

    lookback = _between(arrived, now - timedelta(minutes=t.loaded_lookback_min), now)
    loaded_recently = sum(1 for s in lookback if s.bz is not None and s.bz <= t.bz_south) >= t.loaded_minutes

    recent_n = [s.density for s in _between(arrived, now - timedelta(minutes=5), now) if s.density is not None]
    prior_n = [s.density for s in _between(arrived, now - timedelta(minutes=65), now - timedelta(minutes=5)) if s.density is not None]
    if recent_n and len(prior_n) >= 30 and median(prior_n) > 0:
        r.shock = median(recent_n) > t.shock_density_ratio * median(prior_n)

    # --- GOES onset ---
    r.goes_satellite = pick_goes(inputs, t)
    if r.goes_satellite is None:
        goes_note = "no GOES on the night side"
    else:
        r.onset, r.hp, r.hp_rise, goes_note = goes_onset(inputs.goes[r.goes_satellite], now, t)

    # --- Reach, darkness, context ---
    kp_now = [k.kp for k in inputs.kp if _minutes(now - k.time) <= t.kp_window_min]
    r.kp = max(kp_now) if kp_now else None
    reach = r.kp is not None and r.kp >= t.kp_reach
    if inputs.sun_elevation is not None:
        r.dark = inputs.sun_elevation <= t.sun_dark_elevation
    r.watch, r.watch_reason = watch_active(inputs, t)
    r.g_now, r.g_forecast = inputs.g_now, inputs.g_forecast
    geo = [a for a in inputs.alerts if a.geomagnetic]
    r.alert = max(geo, key=lambda a: a.issued) if geo else None

    # --- Decide ---
    onset = r.onset and loaded_recently
    trigger = onset or r.strong
    if r.loaded:
        why.append(f"Bz <= {t.bz_south:g} for {r.bz_south_fraction:.0%} of the last {t.south_window_min} min")
    if r.shock:
        why.append("density spike - likely shock arrival")
    if r.strong:
        why.append(f"strong driving: mean Bz {r.bz_mean_30:.1f} nT, speed >= {t.strong_speed:g} km/s")
    if r.onset:
        why.append(f"GOES-{r.goes_satellite} Hp up {r.hp_rise:.0f} nT - substorm onset" + ("" if loaded_recently else ", but not loaded beforehand"))
    elif goes_note and (r.loaded or r.strong):
        why.append(goes_note)

    latch = inputs.last_go is not None and now - inputs.last_go < timedelta(minutes=t.go_latch_min)
    can_go = r.fresh and reach and r.dark is True
    if can_go and trigger:
        r.status, r.go_triggered = GO, True
    elif can_go and latch:
        r.status = GO
        why.append("holding go through the expansion phase")
    elif r.fresh and (r.loaded or r.shock or trigger):
        r.status = ELEVATED
        if trigger and not reach:
            why.append(f"Kp {r.kp if r.kp is not None else 'unknown'} < {t.kp_reach:g} - oval likely north of us")
        if trigger and r.dark is not True:
            why.append("not dark yet")
    elif r.watch:
        r.status = WATCH
    if r.watch and r.watch_reason:
        why.append(r.watch_reason)
    r.last_go = now if r.go_triggered else inputs.last_go
    r.reasons = why
    return r
