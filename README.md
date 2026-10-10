# Aurora Watch

A Home Assistant integration that says **go outside now** when aurora is likely visible
from home, using real-time solar wind and the GOES magnetometers rather than Kp. Built for
Wauwatosa, WI (~43N, ~53 deg geomagnetic), on Vince Ledvina's ("The Aurora Guy") substorm
method: **south Bz loads the magnetosphere, a GOES Hp spike marks the release.**

Design and reasoning: [ARCHITECTURE.md](ARCHITECTURE.md).

## Status

| State | Meaning |
|---|---|
| `quiet` | nothing notable |
| `watch` | NOAA says tonight could be active: G2+ now or forecast, a K6+ warning or alert, or a sudden impulse |
| `elevated` | the magnetosphere is loading (Bz south and sustained), a shock has arrived, or go conditions are met in daylight or below the Kp reach |
| `go` | dark, fresh data, Kp >= 5, and either a GOES onset after loading or strong storm-time driving |

`sensor.aurora_watch_status` carries `reasons`, so the dashboard and the push say *why*.

## Install

1. **HACS** - Custom repositories - `https://github.com/worthingtony/ha-aurora-alerts`, category
   Integration - Download - restart Home Assistant.
2. **Settings - Devices and services - Add integration - Aurora Watch.** Nothing to fill in.
   Darkness comes from `sun.sun`.
3. **apexcharts-card** from HACS (Frontend), for the dashboard.
4. **Dashboard:** create a dashboard with url `aurora`, open the raw configuration editor,
   paste [dashboards/aurora.yaml](dashboards/aurora.yaml).
5. **Notifications:** import the two blueprints, then create one automation from each:
   - `https://github.com/worthingtony/ha-aurora-alerts/blob/main/blueprints/automation/aurora_watch/go.yaml`
   - `https://github.com/worthingtony/ha-aurora-alerts/blob/main/blueprints/automation/aurora_watch/watch.yaml`

   On iOS, allow **Time Sensitive Notifications** for the Home Assistant app, or the go push
   arrives as a normal one.

HA's core `aurora` integration (OVATION probability) is unrelated and can coexist.

## Entities

`sensor.aurora_watch_`: `status`, `bz`, `bt`, `solar_wind_speed`, `solar_wind_density`,
`bz_south_fraction`, `minutes_south`, `goes_hp`, `kp_estimated`, `g_scale_now`,
`g_scale_tonight`, `data_age`, `swpc_alert` (full text in `message`),
`binary_sensor.aurora_watch_dark_enough`, and `number.aurora_watch_kp_trigger` (the Kp go
needs, default 5).

## Data

All from NOAA SWPC, free, no key, polled every 60 s (Kp 3 min, alerts and scales 15 min):

- `products/geospace/propagated-solar-wind-1-hour.json` - 1-min Bz, Bt, speed, density,
  time-shifted to **Earth arrival**, so the windows below are about what is hitting us now.
  The 7-day file seeds 4 h of history once at startup.
- `json/goes/{primary,secondary}/magnetometers-6-hour.json` - GOES-19 and GOES-18 Hp.
- `json/planetary_k_index_1m.json` - estimated Kp, 1-min.
- `products/alerts.json`, `products/noaa-scales.json`.

A failed fetch keeps the last good data and `data_age` climbs; **go is impossible past 10
minutes old.**

## Thresholds and tuning

Every number is in `Thresholds` at the top of
[`engine.py`](custom_components/aurora_watch/engine.py). The ones that matter:

| Threshold | Default | Why |
|---|---|---|
| `bz_south` | -10 nT | Vince uses about -5 for Fairbanks, under the oval. At 53 deg geomagnetic the oval has to be pushed south, so we ask for more. |
| `south_window_min` / `south_fraction` | 30 min / 80% | Vince: "around 30 min of sustained, southward-pointing Bz." 80% allows brief excursions north. |
| `loaded_minutes` in `loaded_lookback_min` | 30 in 120 min | An onset only counts if the magnetosphere was loaded. Onsets often follow a northward turning, so this looks back, not at now. |
| `onset_rise_nt` / `onset_decline_nt` | 15 / 20 nT | Hp up 15 nT within 10 min after dropping 20 nT over the prior 2 h: the dipolarization Vince watches for. |
| `goes_night_start_lt` / `goes_night_end_lt` | 20-04 local | Only the satellite near local midnight counts. On the dayside, compression and magnetopause crossings look identical to onsets - replaying 2026-10-10 found ~50 of them. |
| `kp_reach` | 5 | Below this, substorm aurora sits around 60-65 deg geomagnetic, north of our horizon. **Tunable from the UI** as `number.aurora_watch_kp_trigger`; it survives restarts. |
| `strong_bz_mean` / `strong_speed` | -15 nT / 600 km/s | Storm main phase lights the sky without a clean substorm. |
| `max_data_age_min` | 10 | Never go on stale data. |
| `sun_dark_elevation` | -12 deg | Nautical dusk. |
| `go_latch_min` | 30 | Expansion phase lasts 15-30 min; hold go through it. |

**Tuning:** these are starting points. When an alert fires (or doesn't, and you saw aurora),
note the time and look at the Bz and Hp charts. Change one number, add a test from that
night's data, and push a new release.

## Tests

```bash
pip install -r requirements_test.txt
pytest
```

Recorded SWPC data from 2026-10-03 to 2026-10-10 in `tests/fixtures/`: quiet days, a G2 on
Oct 4, and the G2-G3 storm of Oct 10 (Bz to -28.9 nT, speed to 842 km/s, GOES-19
magnetopause crossings, one real GOES-18 dipolarization at 08:16 UTC). The replay never
says go outside the storm.

## Not in v1

- Glendale App's Telegram alerts and the Churchill (NRCan) ground magnetometer as extra
  onset votes.
- **Facebook.** Meta has no Groups API since 2024 and Page access needs business
  verification. Vince's public Page can come in as RSS (rss.app or FetchRSS) through the
  core `feedreader` integration; private groups only through notification emails and the
  core `imap` integration. Neither needs code here.
- An options flow. The Kp trigger is a number entity; the rest live in `engine.py` until
  editing them gets old.
