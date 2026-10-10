# Aurora Watch - architecture (v1 draft, 2026-10-10)

A Home Assistant custom integration that says **go outside now** in Wauwatosa (~43N,
~53 deg geomagnetic), using Vince Ledvina's substorm method rather than Kp.

## The method, in one paragraph

Vince's rule (theauroraguy.com, "A Practical Substorm Guide", 2026-01-05; Edmonton talk,
2026-10-05): **south Bz loads the magnetosphere, and the GOES magnetometer shows the
release.** The GOES Hp line *falls* while the tail stretches (growth, 1-2 h, usually under
south Bz), then *spikes up* at onset (dipolarization). Expansion lasts 15-30 min, and that is
when mid-latitudes see aurora. Kp and OVATION, in his words, "not possible" for timing.
So **Bz loads, GOES Hp triggers, and estimated Kp says whether the oval reaches us.**

## Shape

```
        sources (poll)                engine (pure Python)              Home Assistant
 ----------------------------   -----------------------------   ---------------------------
 L1 wind, propagated   60 s --> |                           |   one coordinator -> entities
 GOES-19/18 Hp         60 s --> |  quiet/watch/elevated/go  | ->  sensor.aurora_status
 est. Kp (1-min)       60 s --> |  + reasons + data age    |    binary_sensor.dark_enough
 alerts, scales       15 min -> |                           |   blueprints -> iPhone
 (v1.1) Glendale, FCC mag ----> |                           |   ApexCharts dashboard
```

- **`engine/`** has no Home Assistant imports. It takes parsed series plus thresholds and
  returns a status, the reasons for it, and each input's age. All the logic lives here, and
  all the tests run here.
- **`sources/`** has one small fetcher and parser per feed. They parse by field name, drop
  nulls, and report the newest timestamp.
- **Home Assistant layer:** one `DataUpdateCoordinator` ticking every 60 s, which refreshes
  each feed on its own interval. A config flow (location from the home zone, darkness from
  `sun.sun`). **No options flow in v1:** thresholds are constants in `engine.Thresholds`, all
  in one place. The exception is the Kp trigger, `number.aurora_watch_kp_trigger`, because
  how far south is worth going out for is a judgement call (Tony, 2026-10-10).
- No new Python dependencies; it uses Home Assistant's own `aiohttp`. HAOS on the Pi 5,
  installed as a HACS custom repo.

## Sources (all verified live 2026-10-10 by fetching them)

| Feed | URL (SWPC) | Why |
|---|---|---|
| L1 wind + IMF, 1-min | `products/geospace/propagated-solar-wind-1-hour.json` (7 KB) | Bz, Bt, speed, density. **Keyed on `propagated_time_tag`** (Earth arrival, ~30 min after the L1 `time_tag`), which gives a free "loading incoming" lead |
| GOES Hp, 1-min | `json/goes/primary/magnetometers-6-hour.json` (GOES-19, 72.5W), `secondary/` (GOES-18, 137W) | Vince's onset signal |
| Estimated Kp, 1-min | `json/planetary_k_index_1m.json` (`estimated_kp`) | does the oval reach 53 deg? *Not* `geospace_pred_est_kp_1_hour.json`: its newest row read 2.3 mid-storm while the rows before it climbed to 7.3 |
| Watch context | `products/alerts.json`, `noaa-scales.json` | `watch` state |
| *v1.1* Glendale | public Telegram preview `t.me/s/GlendaleApp` | independent ground-magnetometer onset alert, the tool Vince uses for "go time" |
| *v1.1* Churchill (FCC) magnetometer | NRCan FDSN, miniSEED, 1-2 min latency | on our meridian: a negative bay there is onset right above the oval |

*`products/solar-wind/*.json`, named in the handoff, now returns 404; SWPC retired those files.
OVATION (936 KB) and hemispheric power were left out of v1 as too heavy for what they add.*

## Status logic (defaults in `engine.Thresholds`)

| Status | Condition |
|---|---|
| `watch` | NOAA G2+ watch/warning/alert, a sudden-impulse alert, or G2+ forecast for tonight |
| `elevated` | **loading:** Bz <= -10 nT for >= 80% of the last 30 min, **or** a shock: density > 2x the prior hour's median |
| `go` | **dark** (sun < -12 deg) **and fresh** (every input <= 10 min old) **and reach** (estimated Kp >= the Kp trigger, default 5), plus either **onset** (loading, then GOES Hp rises >= 15 nT within 10 min after a decline over the prior 120 min) or **strong driving** (mean Bz <= -15 nT over 30 min and speed >= 600 km/s, because storm-time driving that strong lights the sky without a clean substorm) |
| `quiet` | everything else |

GOES guardrails (from replaying today's storm, where a naive rule fired ~50 false onsets):
- **Use the satellite nearest local midnight**, and only between about 20:00 and 04:00
  satellite local time. Dipolarizations show up near midnight; on the dayside, Hp jumps are
  compression and magnetopause crossings. For Wauwatosa evenings that is GOES-19 (local
  midnight at 04:50 UTC), with GOES-18 (09:08 UTC) taking over before dawn. **This gate does
  the real work:** the 15:05 UTC sudden impulse raised GOES-19 Hp 16 nT after a 21 nT dip,
  which is indistinguishable from an onset by shape alone.
- **Throw out samples with Hp < 0 or a jump of more than 50 nT/min.** That is the
  satellite outside the magnetosphere. It removes the worst of a crossing, not all of it.
- *Known gap:* a sudden impulse on the night side will also read as an onset. It usually
  comes with a density shock and often triggers a real substorm, so v1 accepts it.

`go` latches for 30 min (the expansion phase). It **pushes only on a transition into `go`
or a new onset**, never on a timer, so a storm that lasts all night doesn't re-alert every
45 min.

*Why -10 and Kp 5 and not Vince's -5:* his numbers are for Fairbanks, under the oval. A
substorm under Bz -10 alone puts aurora at 60-65 deg geomagnetic, below our horizon. All
the thresholds are placeholders until real events are logged against them.

## Entities (v1)

`aurora_status` (attribute `reasons`), Bz, Bt, speed, density, Bz 30-min south fraction,
minutes south, GOES Hp (the selected satellite, attribute `satellite`), estimated Kp,
G-scale now and forecast, latest SWPC alert headline (the first 255 characters, not the
49 KB file), data age, and `binary_sensor.aurora_dark_enough`.

## Notifications and dashboard

- **Blueprints:** `watch` sends one normal push per evening. `go` sends a time-sensitive
  push with Bz, speed and minutes south, and has an optional critical toggle and an optional
  "clear" note. **Cloud cover check** against the existing weather entity: "go, but 90%
  cloud". Target: `notify.mobile_app_tonys_iphone`.
- **Dashboard:** ApexCharts (install from HACS first). Status tile first, then Bz for 3 h
  with the threshold line, GOES Hp with onsets marked, speed and density, then tiles and
  the alert text. Phone first.

## Tests

`pytest` against the engine using recorded SWPC data, committed gzipped.
**Quiet** = 2026-10-03 to 2026-10-09 (min Bz -19.6, max speed 644). **Storm** = the G2 on
2026-10-10 (Bz to -28.9 nT, speed to 842 km/s, GOES magnetopause crossings, one real GOES-18
dipolarization at 08:16 UTC). Plus synthetic gaps, stale data and a spacecraft switch.

## Phasing

| | Scope |
|---|---|
| **v1** | sources above, engine, entities, config flow, blueprints, dashboard, tests |
| **v1.1** (2026-10-10) | saved spots (zones), loading incoming with a get-ready push, Glendale as a second onset vote. Next: Churchill, follow the phone |
| **later** | Facebook (below), an event log for tuning against what was actually seen |

**Facebook is deliberately outside the integration.** Meta has had no Groups API since
2024-04-22, and Page Public Content Access needs business verification. Vince's public Page
can come in through rss.app or FetchRSS and the core `feedreader` integration. Private
groups can only come in through Facebook's notification emails, read with the core `imap`
integration. Neither needs code here.

## Where it lives

A new repo, **`worthingtony/ha-aurora-alerts`**, holding the code plus this design record.
HACS needs its own repo, which matches the kitchen-stack pattern in `homelab/REPOS.md`.
It has to be **public**: HACS cannot install from a private repo, and nothing in it maps the
network. homelab gets a pointer under `home-automation/`.
