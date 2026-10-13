"""Stage 2's demand and MID rules on synthetic series: a gap longer than MAX_GAP_HH stays empty whole (pandas'
interpolate(limit=n) would fill its first n values), national demand is empty where Elexon published no
transmission demand (it was read as zero before, putting national demand at the embedded generation alone), and a
market index period without traded volume is a gap, not a price of GBP 0/MWh. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import stage2_build_timeseries as S2
from gbpowerdata.common import elexon

UTC = "UTC"


def _idx(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2021-02-16", periods=n, freq="30min", tz=UTC)


def test_short_gaps_are_interpolated_and_long_ones_stay_empty_whole():
    s = pd.Series([1.0, np.nan, np.nan, 4.0] + [5.0] + [np.nan] * 8 + [14.0], index=_idx(14))
    f = S2.fill_short_gaps(s, max_gap=6)
    assert f.iloc[1:3].tolist() == [2.0, 3.0]
    assert f.iloc[5:13].isna().all()                      # an 8-period gap: nothing filled, not its first 6
    assert S2.fill_short_gaps(pd.Series([np.nan, 1.0, np.nan], index=_idx(3))).isna().tolist() == [True, False, True]


def test_national_demand_is_empty_where_transmission_demand_is_missing():
    idx = _idx(60)
    itsdo = pd.Series(25000.0, index=idx)
    itsdo.iloc[10:52] = np.nan                             # a whole-day hole, as on 16 Feb 2021
    itsdo.iloc[3] = np.nan                                 # a single missing period
    esp = pd.DataFrame({"embedded_wind_mw": 2000.0, "embedded_solar_mw": 500.0}, index=idx)
    d = S2.demand_table(itsdo, esp)
    assert d["national_demand_mw"].iloc[10:52].isna().all()
    assert (d["transmission_demand_source"].iloc[10:52] == "missing").all()
    assert d.loc[3, "transmission_demand_source"] == "interpolated" and d.loc[3, "national_demand_mw"] == 27500.0
    assert d.loc[0, "national_demand_mw"] == 27500.0 and d.loc[0, "transmission_demand_source"] == "ITSDO"
    assert list(d.columns) == ["startTime", "transmission_demand_mw", "embedded_wind_mw", "embedded_solar_mw",
                               "national_demand_mw", "transmission_demand_source"]


def test_a_market_index_period_without_volume_is_a_gap_not_a_zero_price(tmp_path):
    t = pd.date_range("2019-03-01", periods=4, freq="30min", tz=UTC)
    pd.DataFrame({"startTime": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "dataProvider": "APXMIDP",
                  "settlementDate": "2019-03-01", "settlementPeriod": [1, 2, 3, 4],
                  "price": [50.0, 0.0, 52.0, 0.0], "volume": [100.0, 0.0, 80.0, 0.0]}).to_csv(
        tmp_path / "mid_apx_20190301_20190302.csv", index=False)
    m = elexon.mid_prices(tmp_path)
    assert m.index.tolist() == [t[0], t[2]]                # the two zero-volume periods are left out
    target = S2.mid_target(m.reindex(t), pd.Series(dtype=float))
    assert target["mid_source"].tolist() == ["APXMIDP", "interpolated", "APXMIDP", "missing"]
    assert target["price_gbp_per_mwh"].iloc[1] == pytest.approx(51.0)
    assert np.isnan(target["price_gbp_per_mwh"].iloc[3])   # a trailing gap is not extrapolated


def test_n2ex_fills_the_market_index_only_where_it_is_given():
    t = pd.date_range("2020-07-07", periods=3, freq="30min", tz=UTC)
    target = S2.mid_target(pd.Series([40.0, np.nan, 42.0], index=t), pd.Series([45.0], index=[t[1]]))
    assert target["mid_source"].tolist() == ["APXMIDP", "N2EX", "APXMIDP"]
    assert target["price_gbp_per_mwh"].iloc[1] == 45.0
