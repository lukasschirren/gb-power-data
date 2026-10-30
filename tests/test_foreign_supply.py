"""The neighbours' residual demand (pull.entsoe_residual_pull) and supply slope (build.foreign_supply) on synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gbpowerdata.build import foreign_supply as F
from gbpowerdata.pull import entsoe_residual_pull as P


def test_short_gaps_are_filled_and_counted_long_gaps_left():
    idx = pd.date_range("2023-01-01", periods=9, freq="h", tz="UTC")
    s = pd.Series([1.0, np.nan, np.nan, 4.0, np.nan, np.nan, np.nan, np.nan, 9.0], index=idx)
    out, n = P._fill_short_gaps(s, max_gap=3)
    assert n == 2 and out.iloc[1:3].notna().all() and out.iloc[4:8].isna().all()
    assert list(out.iloc[1:3].round(6)) == [2.0, 3.0]
    same, zero = P._fill_short_gaps(s, max_gap=0)
    assert zero == 0 and same.equals(s)


def test_to_hourly_is_duration_weighted_and_drops_partial_hours():
    t = pd.to_datetime(["2023-01-01 00:00", "2023-01-01 00:30", "2023-01-01 01:00"], utc=True)
    df = pd.DataFrame({"value": [100.0, 200.0, 300.0], "step_min": [30.0, 30.0, 30.0]},
                      index=pd.DatetimeIndex(t, name="deliveryStart"))
    out = P._to_hourly(df)
    assert out.iloc[0] == 150.0 and np.isnan(out.iloc[1])     # 01:00 has only 30 of 60 minutes


def test_slope_recovers_a_linear_supply_curve():
    idx = pd.date_range("2023-01-01", periods=2000, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    resid = pd.Series(rng.uniform(5000, 20000, 2000), index=idx)
    price = 10 + 0.004 * resid
    out = F.slope(price, resid)
    assert abs(out["slope_gbp_per_mw"] - 0.004) < 1e-9 and out["r2"] > 0.999 and 900 < out["n"] < 1100


def test_slope_uses_the_low_residual_half_within_each_year():
    idx = pd.date_range("2022-01-01", periods=17520, freq="h", tz="UTC")
    resid = pd.Series(np.tile(np.linspace(0, 10000, 8760), 2), index=idx)
    price = pd.Series(np.where(idx.year == 2022, 50.0, 150.0), index=idx) + 0.01 * resid   # fuel shifts the level
    out = F.slope(price, resid)
    assert abs(out["slope_gbp_per_mw"] - 0.01) < 1e-9 and out["n"] == 2 * 4380
