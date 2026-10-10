"""Replays of recorded SWPC data, 2026-10-03 to 2026-10-10.

The week holds quiet days (Oct 6-9, Kp <= 4), a G2 on Oct 4, and a G2-G3 storm on
Oct 10 (Bz to -28.9 nT, speed to 842 km/s, GOES-19 magnetopause crossings late morning).
Darkness is forced in most tests, so they test the space weather, not the clock.
"""

from datetime import timedelta

from conftest import engine, sources, utc


def walk(replay, start, end, step=5, **kw):
    t, last_go = utc(start), None
    while t <= utc(end):
        r = engine.evaluate(replay.inputs(t, last_go=last_go, **kw))
        if r.go_triggered:
            last_go = t
        yield t, r
        t += timedelta(minutes=step)


# --- Parsers ---------------------------------------------------------------------


def test_wind_parses_by_header_name(replay):
    assert len(replay.wind) > 9000
    s = replay.wind[-1]
    assert s.arrives > s.observed, "propagated time is Earth arrival, after L1"
    assert sources.parse_wind([["speed", "time_tag"], [400, "x"]]) == []  # missing columns: skip, don't raise


def test_goes_longitudes_are_degrees_east(replay):
    assert replay.longitudes[19] == -72.5 and replay.longitudes[18] == -137.0


def test_scales_and_alert_headline():
    assert sources.parse_scales({"0": {"G": {"Scale": "2"}}, "1": {"G": {"Scale": "1"}}, "2": {"G": {"Scale": "3"}}}) == (2, 3)
    assert sources.parse_scales({}) == (None, None)
    a = sources.parse_alerts([{"product_id": "K06A", "issue_datetime": "2026-10-10 17:18:13.507",
                               "message": "Space Weather Message Code: ALTK06\r\nALERT: Geomagnetic K-index of 6 \r\n"}])[0]
    assert a.headline == "ALERT: Geomagnetic K-index of 6" and a.geomagnetic


# --- Quiet: no false alarms --------------------------------------------------------


def test_quiet_days_never_go(replay):
    statuses = {r.status for _, r in walk(replay, "2026-10-06T00:00:00", "2026-10-09T23:55:00")}
    assert engine.GO not in statuses


def test_whole_week_only_goes_during_the_storm(replay):
    gos = [t for t, r in walk(replay, "2026-10-03T22:00:00", "2026-10-10T17:58:00") if r.status == engine.GO]
    assert gos and all(t >= utc("2026-10-10T15:00:00") for t in gos)


# --- Storm ---------------------------------------------------------------------


def test_storm_is_go_when_dark(replay):
    r = engine.evaluate(replay.inputs(utc("2026-10-10T17:40:00")))
    assert r.status == engine.GO and r.go_triggered
    assert r.strong and r.loaded and r.fresh
    assert r.bz <= -10 and r.speed >= 600 and r.kp >= 5
    assert r.minutes_south >= 15


def test_storm_in_daylight_is_elevated_not_go(replay):
    r = engine.evaluate(replay.inputs(utc("2026-10-10T17:40:00"), sun_elevation=30.0))
    assert r.status == engine.ELEVATED
    assert "not dark yet" in r.reasons


def test_stale_data_never_goes(replay):
    now = utc("2026-10-10T17:40:00")
    inputs = replay.inputs(now)
    inputs.wind = [s for s in inputs.wind if s.arrives <= now - timedelta(minutes=15)]
    r = engine.evaluate(inputs)
    assert not r.fresh and r.status != engine.GO
    assert "solar wind data stale" in r.reasons


def test_normal_swpc_lag_is_still_fresh(replay):
    """The propagated product runs 8-11 min behind L1 (19:15:42 UTC: newest row 19:05).
    That is normal and must not block go."""
    now = utc("2026-10-10T17:40:00")
    inputs = replay.inputs(now)
    inputs.wind = [s for s in inputs.wind if s.observed <= now - timedelta(minutes=11)]
    r = engine.evaluate(inputs)
    assert r.data_age_min >= 11 and r.fresh and r.status == engine.GO


def test_missing_data_is_quiet_not_a_crash(replay):
    inputs = replay.inputs(utc("2026-10-10T17:40:00"))
    inputs.wind, inputs.goes, inputs.kp = [], {}, []
    r = engine.evaluate(inputs)
    assert r.status in (engine.QUIET, engine.WATCH) and r.data_age_min is None


def test_one_late_update_does_not_drop_go(replay):
    """Review finding: go -> 12-min-old data -> quiet sent 'quiet again', then the
    cooldown ate the real go a minute later. The latch now holds through it."""
    now = utc("2026-10-10T17:40:00")
    inputs = replay.inputs(now, last_go=now - timedelta(minutes=1))
    inputs.wind = [s for s in inputs.wind if s.arrives <= now - timedelta(minutes=12)]
    r = engine.evaluate(inputs)
    assert not r.fresh and r.status == engine.GO


def test_reasons_do_not_change_tick_to_tick(replay):
    """Stable text keeps the recorder from writing a new attributes row every minute."""
    a = engine.evaluate(replay.inputs(utc("2026-10-10T17:35:00")))
    b = engine.evaluate(replay.inputs(utc("2026-10-10T17:40:00")))
    assert a.status == b.status == engine.GO and a.reasons == b.reasons


def test_old_alerts_are_not_shown(replay):
    r = engine.evaluate(replay.inputs(utc("2026-10-08T12:00:00"), sun_elevation=30.0))
    assert r.alert is None or utc("2026-10-08T12:00:00") - r.alert.issued < timedelta(hours=24)


def test_go_latches_through_expansion(replay):
    now = utc("2026-10-10T17:40:00")
    inputs = replay.inputs(now, last_go=now - timedelta(minutes=10))
    inputs.wind = [s for s in inputs.wind if s.bz is None or s.arrives < now - timedelta(minutes=30)] + [
        engine.WindSample(now - timedelta(minutes=2), now - timedelta(minutes=1), 3.0, 10.0, 700.0, 10.0)]
    r = engine.evaluate(inputs)
    assert r.status == engine.GO and not r.go_triggered
    assert "holding go through the expansion phase" in r.reasons


# --- GOES onset (Vince's signal) -----------------------------------------------------


def test_real_dipolarization_is_detected(replay):
    """GOES-18 at 23:10 local time, Hp 22 -> 56 nT: a real onset, found by the review."""
    r = engine.evaluate(replay.inputs(utc("2026-10-10T08:15:00")))
    assert r.goes_satellite == 18 and r.onset and r.hp_rise >= 15
    assert r.status != engine.GO, "Bz wasn't loaded and Kp was ~3: oval too far north for us"


def test_dayside_crossings_and_compression_are_not_onsets(replay):
    """GOES-19, 15:00-17:58 UTC Oct 10 (10-13 LT). A sudden impulse at ~15:05 raised Hp
    16 nT after a 21 nT dip, then magnetopause crossings swung it +148 -> -152 -> +202.

    The Hp filter alone still sees ~50 "onsets" here: compression looks exactly like a
    dipolarization. The local-time gate is what stops them, so test that.
    """
    hits = [t for t, r in walk(replay, "2026-10-10T15:00:00", "2026-10-10T17:58:00", step=1) if r.onset]
    assert hits == []


def test_hp_is_shown_in_daytime_but_onsets_are_not_read(replay):
    """Installed 2026-10-10: goes_hp sat at unknown all afternoon because both GOES were
    on the dayside. It now shows the satellite nearest midnight, flagged as dayside."""
    r = engine.evaluate(replay.inputs(utc("2026-10-10T17:00:00")))
    assert r.goes_satellite == 18 and r.hp is not None  # 07:52 local beats GOES-19 at 12:10
    assert not r.goes_night_side and not r.onset and r.hp_rise is None


def test_satellite_nearest_local_midnight_is_used(replay):
    inputs = replay.inputs(utc("2026-10-10T04:50:00"))  # GOES-19 at local midnight
    assert engine.pick_goes(inputs, engine.Thresholds()) == 19
    inputs = replay.inputs(utc("2026-10-10T09:00:00"))  # GOES-19 near 4 LT, GOES-18 near midnight
    assert engine.pick_goes(inputs, engine.Thresholds()) == 18
    inputs = replay.inputs(utc("2026-10-10T17:00:00"))  # both on the dayside
    assert engine.pick_goes(inputs, engine.Thresholds()) is None


# --- Kp and watch ------------------------------------------------------------------


def test_kp_survives_the_three_hour_reset():
    """SWPC's 1-min estimate drops to 0 at each 3-hour boundary (7.0 then 0.0 at 18:00)."""
    now = utc("2026-10-10T18:01:00")
    kp = [engine.KpSample(now - timedelta(minutes=m), 7.0) for m in range(2, 20)] + [engine.KpSample(now, 0.0)]
    r = engine.evaluate(engine.Inputs(now=now, wind=[], goes={}, goes_longitude={}, kp=kp, alerts=[]))
    assert r.kp == 7.0


def test_watch_from_noaa(replay):
    r = engine.evaluate(replay.inputs(utc("2026-10-10T17:25:00"), sun_elevation=30.0))
    assert r.watch and r.alert.headline.startswith("ALERT: Geomagnetic K-index of 6")
    quiet = engine.evaluate(replay.inputs(utc("2026-10-07T12:00:00"), sun_elevation=30.0))
    assert not quiet.watch and quiet.status == engine.QUIET
    forecast = engine.evaluate(replay.inputs(utc("2026-10-07T12:00:00"), sun_elevation=30.0, g_forecast=2))
    assert forecast.status == engine.WATCH


# --- Glendale ---------------------------------------------------------------------


def test_glendale_page_parses(replay):
    levels = [(g.posted.strftime("%H:%M"), g.level) for g in replay.glendale if g.posted.day == 10]
    assert ("08:29", 2) in levels and ("17:48", 6) in levels
    shock = next(g for g in replay.glendale if g.text.startswith("Interplanetary shock"))
    assert shock.arrives == utc("2026-10-10T15:31:00") and shock.level == 0
    assert sources.parse_glendale("<html>nothing here</html>") == []


def test_glendale_onset_counts_only_after_loading(replay):
    """Extreme alert 17:48, Bz loaded: an onset vote. Orange 08:29, Bz not loaded: noted only."""
    r = engine.evaluate(replay.inputs(utc("2026-10-10T17:52:00")))
    assert r.glendale_onset and r.glendale.level == 6 and r.status == engine.GO
    early = engine.evaluate(replay.inputs(utc("2026-10-10T08:35:00")))
    assert early.glendale_onset and early.status != engine.GO
    assert any("not loaded beforehand" in why for why in early.reasons)


def test_glendale_alone_never_makes_go_without_reach(replay):
    r = engine.evaluate(replay.inputs(utc("2026-10-10T08:35:00"), sun_elevation=-30.0))
    assert r.kp < 5 and r.status != engine.GO


# --- Loading incoming -------------------------------------------------------------


def test_loading_incoming_gives_lead_time(replay):
    """Bz -20 nT reached Earth ~17:02 UTC Oct 10; the L1 data showed it from 16:35."""
    r = engine.evaluate(replay.inputs(utc("2026-10-10T16:35:00"), glendale=False))
    assert r.incoming and not r.loaded
    assert (r.incoming_at - utc("2026-10-10T16:35:00")) >= timedelta(minutes=20)
    assert "arriving ~" in r.incoming_reason


def test_no_incoming_on_quiet_days(replay):
    hits = [t for t, r in walk(replay, "2026-10-06T00:00:00", "2026-10-09T23:50:00", step=10, glendale=False) if r.incoming]
    assert hits == []


def test_glendale_shock_warning_is_incoming(replay):
    r = engine.evaluate(replay.inputs(utc("2026-10-10T14:50:00")))
    assert r.incoming and "shock" in r.incoming_reason and r.incoming_at == utc("2026-10-10T15:31:00")
