"""The thermal units' run and down times (gbpowerdata.build.unit_runs) on synthetic half-hours: on and off against the
unit's full output, spells censored at a gap or an end of the data, the two-shift runs, the statistics per year, the
declared MNZT in force over a year without the 999 sentinel, the metering read on its half-hour's start, and the
B1610 puller's named units. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import unit_runs as U

UTC = "UTC"


def levels(values, start="2025-01-01 00:00"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="30min", tz=UTC), dtype=float)


def test_a_half_hour_is_on_at_a_tenth_of_full_output_and_a_missing_one_is_unknown():
    lv = levels([0.0, 30.0, 45.0, 400.0, -2.0, 400.0])
    lv = lv.drop(lv.index[4])                                   # no reading in the fifth half-hour
    state, full = U.states(lv)
    assert full == pytest.approx(400.0)
    assert state.tolist()[:4] == [0.0, 0.0, 1.0, 1.0] and np.isnan(state.iat[4]) and state.iat[5] == 1.0


def test_spells_are_censored_next_to_a_gap_or_an_end():
    state = levels([0, 0, 1, 1, 1, 0, 0, 1, np.nan, 1, 0])
    s = U.spells(state)
    assert s["state"].tolist() == ["down", "run", "down", "run", "run", "down"]
    assert s["hours"].tolist() == [1.0, 1.5, 1.0, 0.5, 0.5, 0.5]
    assert s["censored"].tolist() == [True, False, False, True, True, True]
    assert s["end"].iat[1] == pd.Timestamp("2025-01-01 02:30", tz=UTC)


def test_a_two_shift_run_is_short_and_followed_by_a_short_down():
    s = pd.DataFrame({"state": ["run", "down", "run", "down", "run", "down"],
                      "hours": [16.0, 8.0, 30.0, 6.0, 10.0, 40.0],
                      "censored": [False, False, False, False, False, False]})
    assert U.two_shift(s).tolist() == [True, False, False, False, False, False]
    s.loc[1, "censored"] = True                                 # the down after it ran into a gap: not known
    assert not U.two_shift(s).iat[0]


def test_the_statistics_of_a_year_count_only_uncensored_spells():
    # off 2 h, on 7 h, off 3 h, on 3 h, off to the end of the data: one whole run and one whole down
    lv = levels([0.0] * 4 + [400.0] * 14 + [0.0] * 6 + [400.0] * 6 + [0.0] * 4)
    s, per_year, full = U.measure(lv, years=(2025,))
    row = per_year.iloc[0]
    assert row["year"] == 2025 and row["hours_observed"] == 17.0 and row["hours_on"] == 10.0 and row["starts"] == 2
    assert row["n_runs"] == 2 and row["run_h_p50"] == pytest.approx(5.0) and row["run_share_under_6h"] == 0.5
    assert row["n_downs"] == 1 and row["down_h_p10"] == 3.0 and row["two_shift_share"] == 0.5
    assert s["censored"].tolist() == [True, False, False, False, True]


def test_the_declared_value_is_weighted_by_the_time_it_was_in_force_without_the_sentinel():
    d = pd.DataFrame({"time": pd.to_datetime(["2024-11-01", "2025-04-01", "2025-07-01", "2025-10-01"], utc=True),
                      "minutes": [360.0, 999.0, 240.0, 240.0]})
    start, end = pd.Timestamp("2025-01-01", tz=UTC), pd.Timestamp("2026-01-01", tz=UTC)
    mean, share = U.in_force(d, start, end)
    days = {"360": 90.0, "999": 91.0, "240": 184.0}              # Jan-Mar, Apr-Jun, Jul-Dec
    assert share == pytest.approx(days["999"] / 365)
    assert mean == pytest.approx((6.0 * days["360"] + 4.0 * days["240"]) / (days["360"] + days["240"]))
    first = pd.DataFrame({"time": pd.to_datetime(["2025-07-01"], utc=True), "minutes": [120.0]})
    assert U.in_force(first, start, end) == (pytest.approx(2.0), 0.0)     # first declared in July: from then
    assert U.in_force(first.iloc[:0], start, end) == (pytest.approx(np.nan, nan_ok=True),
                                                      pytest.approx(np.nan, nan_ok=True))


def test_declarations_take_the_elexon_id_or_map_the_ngc_id(tmp_path):
    folder = tmp_path / "bm_dynamic"
    folder.mkdir()
    pd.DataFrame({"dataset": ["MNZT", "MNZT"], "time": ["2025-01-05T10:00:00Z", "2025-02-05T10:00:00Z"],
                  "periodMin": [360, 300], "nationalGridBmUnit": ["ABC-1", "XYZ-1"],
                  "bmUnit": ["T_ABC-1", None]}).to_csv(folder / "submissions_MNZT_2025-01.csv", index=False)
    pd.DataFrame(columns=["dataset", "time", "notice", "nationalGridBmUnit", "bmUnit"]).to_csv(
        folder / "submissions_NDZ_2025-01.csv", index=False)                          # a quiet month
    pd.DataFrame({"nationalGridBmUnit": ["XYZ-1"], "elexonBmUnit": ["E_XYZ-1"]}).to_csv(
        tmp_path / "bm_units_20260101.csv", index=False)
    d = U.declarations(tmp_path)
    assert sorted(zip(d["unit_id"], d["minutes"])) == [("E_XYZ-1", 300.0), ("T_ABC-1", 360.0)]
    y = U.declared_by_year(d, years=(2025,), now=pd.Timestamp("2026-06-01", tz=UTC))
    assert set(y.columns) >= {"unit_id", "year", "mnzt_h", "mnzt_share_999"}
    assert y.set_index("unit_id").at["T_ABC-1", "mnzt_h"] == pytest.approx(6.0)


def test_metering_is_keyed_on_the_start_of_its_half_hour(tmp_path):
    f = tmp_path / "T_X-1.csv"
    pd.DataFrame({"bmUnit": ["T_X-1"] * 2, "settlementDate": ["2024-07-01"] * 2, "settlementPeriod": [1, 2],
                  "halfHourEndTime": ["2024-06-30T23:30:00", "2024-07-01T00:00:00"], "quantity": [100.0, 150.0]}
                 ).to_csv(f, index=False)
    mw = U.b1610_levels(f)
    assert mw.index[0] == pd.Timestamp("2024-06-30 23:00", tz=UTC) and mw.tolist() == [200.0, 300.0]


def test_the_b1610_puller_pulls_the_named_units_instead_of_the_register(monkeypatch, tmp_path):
    from gbpowerdata.pull import b1610_pull as P

    pulled = []
    monkeypatch.setattr(P, "OUT", tmp_path)
    monkeypatch.setattr(P, "pull_unit", lambda u, years: pulled.append((u, tuple(years))))
    monkeypatch.setattr(P, "thermal_units", lambda: pytest.fail("the register is not read when units are named"))
    P.main(["b1610_pull", "--units", "E_SHOS-1", "E_GYAR-1", "--start", "2024-01-01", "--end", "2026-01-01"])
    assert pulled == [("E_SHOS-1", (2024, 2025)), ("E_GYAR-1", (2024, 2025))]
