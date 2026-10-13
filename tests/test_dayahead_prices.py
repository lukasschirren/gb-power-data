"""The GB day-ahead blend (gbpowerdata.build.build_dayahead_prices) on synthetic prices and volumes: weighted by the
volume each auction traded where both have one, the plain mean (marked) where one does not, one venue alone where
only one has a price; and the N2EX volume taken from the curve checks before the research code's bid panel. No
data/ and no licensed data needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import build_dayahead_prices as DA

UTC = "UTC"


def test_the_blend_is_volume_weighted_and_says_where_it_is_not():
    t = pd.date_range("2023-01-01", periods=4, freq="30min", tz=UTC)
    n = pd.Series([100.0, 100.0, 100.0, 90.0], index=t)
    e = pd.Series([120.0, 120.0, 120.0, np.nan], index=t)
    v_n = pd.Series([3000.0, 3000.0, np.nan, 3000.0], index=t)     # the third half-hour has no N2EX volume
    v_e = pd.Series([1000.0, 1000.0, 1000.0, np.nan], index=t)
    blend, basis = DA._blend(n, e, v_n, v_e)
    assert blend.iloc[0] == pytest.approx((100 * 3000 + 120 * 1000) / 4000)
    assert blend.iloc[2] == pytest.approx(110.0)                     # the mean, not EPEX alone
    assert blend.iloc[3] == 90.0
    assert basis.tolist() == ["volume", "volume", "mean", "n2ex"]


def test_the_n2ex_volume_comes_from_the_curve_checks_before_the_bid_panel(tmp_path, monkeypatch):
    pd.DataFrame({"deliveryStart": ["2023-06-01T10:00:00Z"], "traded_mwh": [12000.0]}).to_csv(
        tmp_path / "n2ex_curve_checks_2023.csv", index=False)
    pd.DataFrame({"deliveryStart": ["2023-06-01T10:00:00Z"], "cleared_volume_mw": [9000.0]}).to_csv(
        tmp_path / "n2ex_bid_panel_2023.csv", index=False)
    monkeypatch.setitem(DA.VOLUME_SOURCES, "n2ex", [(tmp_path, "n2ex_curve_checks_*.csv", "traded_mwh"),
                                                    (tmp_path, "n2ex_bid_panel_*.csv", "cleared_volume_mw")])
    v = DA._load_volume("n2ex")
    assert v.tolist() == [12000.0, 12000.0]                        # the hour on both of its half-hours
    assert v.index[1] == pd.Timestamp("2023-06-01 10:30", tz=UTC)
    (tmp_path / "n2ex_curve_checks_2023.csv").unlink()
    assert DA._load_volume("n2ex").iloc[0] == 9000.0               # the fallback
