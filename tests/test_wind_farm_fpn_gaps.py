"""FPN notification gaps of the transmission wind farms (gbpowerdata.build.stage2d_wind_farms).

Stage 2d writes a farm's FPN with a notification gap read as 0 after interpolating up to 2 h, and
the share of the farm's capacity that is in service but unnotified (wind_farm_fpn_gaps_{year}.csv).
A unit is in service from its first power (or the record's start) to its last notification, so a
missing notification before commissioning or after decommissioning is a genuine zero, not a gap;
and only a hole in the pull (most of the year's in-service units silent) is a gap, so a unit
silent on its own while commissioning is a genuine zero too.

Synthetic: the MW series is what the pre-change unit_fpn produced; the gap share under
commissioning, partial-unit gaps, all units missing and decommissioning.
"""
import numpy as np
import pandas as pd

from gbpowerdata.build import stage2d_wind_farms as s2d

IDX = pd.date_range("2020-01-01", periods=96, freq="30min", tz="UTC")


def _notes(slots, mw) -> pd.DataFrame:
    """Raw notifications (the data/raw/fpn/{bmu}.csv columns) at the half-hours `slots` of IDX."""
    slots = np.asarray(list(slots))
    t0 = IDX[slots]
    mw = np.broadcast_to(np.asarray(mw, dtype=float), slots.shape)
    return pd.DataFrame({"timeFrom": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "timeTo": (t0 + pd.Timedelta("30min")).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "levelFrom": mw, "levelTo": mw})


def _unit_fpn_before(d: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.Series:
    """stage2d.unit_fpn as it was before the gap file (29 Sep 2026), on a frame instead of a file."""
    d = d[d["timeFrom"].str.startswith(str(idx[0].year))]
    if d.empty:
        return pd.Series(0.0, index=idx)
    t0 = pd.to_datetime(d["timeFrom"], utc=True)
    t1 = pd.to_datetime(d["timeTo"], utc=True)
    frac = (t1 - t0).dt.total_seconds() / (30 * 60.0)
    mw = ((d["levelFrom"] + d["levelTo"]) / 2.0 * frac).groupby(t0.dt.floor("30min")).sum()
    s = mw.reindex(idx)
    return s.interpolate(limit=4, limit_area="inside").fillna(0.0).clip(lower=0.0)


# ---------------------------------------------------------------------------------------- stage 2d
def test_mw_series_is_unchanged_and_mask_marks_what_interpolation_leaves():
    rng = np.random.default_rng(3)
    slots = [i for i in range(96) if not (10 <= i <= 12 or 30 <= i <= 39)]   # a 1.5 h and a 5 h gap
    d = _notes(slots, rng.uniform(0, 80, len(slots)))
    mw, ok = s2d.fpn_from_notifications(d, IDX)
    ref = _unit_fpn_before(d, IDX)
    assert np.array_equal(mw.to_numpy(), ref.to_numpy())                   # bit-identical
    # the 3-slot gap is bridged; pandas' limit fills the first 4 slots of the 10-slot one too
    assert ok[10:13].all() and ok[30:34].all()
    assert (~ok[34:40]).all() and ok.sum() == 96 - 6
    assert (mw.to_numpy()[~ok] == 0.0).all()                                 # the file reads the gap as 0


def test_no_notification_in_the_year_is_all_gap():
    mw, ok = s2d.fpn_from_notifications(_notes(range(96), 5.0).iloc[:0], IDX)
    assert (mw == 0.0).all() and not ok.any()


def test_service_start_from_the_map():
    pre = pd.Series(dict(fpn_state="pre_record", first_power=np.nan,
                         fpn_record_start="2016-03-01 01:00:00+00:00"))
    obs = pd.Series(dict(fpn_state="observed", first_power="2020-01-01 12:00:00+00:00",
                         fpn_record_start="2016-03-01 01:00:00+00:00"))
    assert s2d.service_start(pre) == pd.Timestamp("2016-03-01 01:00", tz="UTC")
    assert s2d.service_start(obs) == pd.Timestamp("2020-01-01 12:00", tz="UTC")
    assert pd.isna(s2d.service_start(pd.Series(dict(fpn_state="never", first_power=np.nan,
                                                    fpn_record_start="2016-03-01"))))


def test_gap_share_commissioning_partial_and_whole_farm_gaps():
    # A: 100 MW, in service all along; missing 60-71 (whole-farm hole) and 80-89 (A alone)
    a_slots = [i for i in range(96) if not (60 <= i <= 71 or 80 <= i <= 89)]
    # B: 50 MW, notifies zeros from slot 20 while being built (missing 30-40 then), first power at
    # slot 48, then the same 60-71 hole
    b_slots = [i for i in range(20, 96) if not (30 <= i <= 40 or 60 <= i <= 71)]
    b_mw = np.where(np.asarray(b_slots) >= 48, 20.0, 0.0)
    (_, ok_a), (_, ok_b) = (s2d.fpn_from_notifications(_notes(a_slots, 40.0), IDX),
                            s2d.fpn_from_notifications(_notes(b_slots, b_mw), IDX))
    live_a = s2d.in_service_mask(IDX, pd.Timestamp("2016-03-01 01:00", tz="UTC"), IDX[-1])
    live_b = s2d.in_service_mask(IDX, IDX[48], IDX[-1])
    s = s2d.gap_share([ok_a, ok_b], [live_a, live_b], [100.0, 50.0], 150.0)
    want = np.zeros(96)
    want[64:72] = 1.0                        # 60-63 interpolated; both units in service and silent
    want[84:90] = 100.0 / 150.0              # A alone, after its 2 h of interpolation
    np.testing.assert_allclose(s, want)      # B before first power (0-19, 30-40): genuine zero
    assert s2d.full_service(IDX, [live_a, live_b]) == (IDX[48], IDX[-1])


def test_gap_share_decommissioned_unit_is_no_gap():
    ok = np.zeros(96, dtype=bool)
    ok[:70] = True                           # notifies until slot 69, then nothing
    live = s2d.in_service_mask(IDX, IDX[0], IDX[69])
    assert s2d.gap_share([ok], [live], [30.0], 30.0).sum() == 0.0
    live_on = s2d.in_service_mask(IDX, IDX[0], pd.NaT)          # no known end: the silence is a gap
    np.testing.assert_allclose(s2d.gap_share([ok], [live_on], [30.0], 30.0)[70:], 1.0)
    assert not s2d.in_service_mask(IDX, pd.NaT, IDX[-1]).any()


def test_a_unit_silent_on_its_own_is_no_gap_only_a_pull_hole_is():
    """Moray East's T_MOWEO-1 in June 2021: a few test half-hours of power, then silence while the rest of
    the fleet notifies, then notified zeros. That silence is commissioning, a genuine zero, not a hole in
    the pull; the hole in which every unit is silent stays a gap (stage 2d docstring, pull hole)."""
    hole_slots = set(range(60, 72))                          # the pull misses every unit here
    fleet = [_notes([i for i in range(96) if i not in hole_slots], 30.0) for _ in range(4)]
    # the commissioning unit: zeros 0-19, test power 20-22, silent 23-49, zeros from 50 (and the hole)
    new_slots = [i for i in range(96) if not (23 <= i <= 49) and i not in hole_slots]
    new_mw = np.where((np.asarray(new_slots) >= 20) & (np.asarray(new_slots) <= 22), 1.0, 0.0)
    oks = [s2d.fpn_from_notifications(d, IDX)[1] for d in fleet + [_notes(new_slots, new_mw)]]
    lives = [s2d.in_service_mask(IDX, IDX[0], IDX[-1])] * 4 + [s2d.in_service_mask(IDX, IDX[20], IDX[-1])]
    hole = s2d.pull_holes(oks, lives)
    want_hole = np.zeros(96, dtype=bool)
    want_hole[64:72] = True                                  # 60-63 interpolated for every unit
    np.testing.assert_array_equal(hole, want_hole)
    s = s2d.gap_share(oks[4:], lives[4:], [100.0], 100.0, hole=hole)
    np.testing.assert_array_equal(s, want_hole.astype(float))           # the silence 27-49 is no gap
    s_unit = s2d.gap_share(oks[4:], lives[4:], [100.0], 100.0)          # without the pull-hole rule it was
    assert (s_unit[27:50] == 1.0).all() and (s_unit[64:72] == 1.0).all()
    # half the fleet silent is a hole at the 0.5 threshold; fewer is not; no unit in service, no hole
    half = [np.ones(96, dtype=bool)] * 2 + [np.zeros(96, dtype=bool)] * 2
    assert s2d.pull_holes(half, [np.ones(96, dtype=bool)] * 4).all()
    assert not s2d.pull_holes(half[:3] + [np.ones(96, dtype=bool)], [np.ones(96, dtype=bool)] * 4).any()
    assert not s2d.pull_holes([np.zeros(96, dtype=bool)], [np.zeros(96, dtype=bool)]).any()
