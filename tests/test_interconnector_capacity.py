"""The interconnector table (build.interconnector_capacity): the gap fill, the rated series and a missing source."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import interconnector_capacity as I


def test_fill_unpublished_uses_the_median_of_the_windows_either_side():
    idx = pd.date_range("2023-01-01", periods=24 * 90, freq="h", tz="UTC")
    s = pd.Series(1000.0, index=idx)
    s.iloc[: 24 * 40] = 800.0                     # a lasting limit before the gap
    s.iloc[24 * 40: 24 * 50] = np.nan             # ten unpublished days
    filled, flag = I.fill_unpublished(s, days=30)
    assert (filled.iloc[24 * 40: 24 * 50] == 900.0).all()     # the median of 800s and 1000s either side
    assert flag.iloc[24 * 40: 24 * 50].all() and not flag.iloc[: 24 * 40].any() and not flag.iloc[24 * 50:].any()
    assert (filled.iloc[: 24 * 40] == 800.0).all() and (filled.iloc[24 * 50:] == 1000.0).all()


def test_fill_unpublished_leaves_a_complete_series_alone():
    idx = pd.date_range("2023-01-01", periods=48, freq="h", tz="UTC")
    s = pd.Series(np.arange(48, dtype=float), index=idx)
    filled, flag = I.fill_unpublished(s)
    assert filled.equals(s) and not flag.any()


def test_rated_capacity_adds_each_cable_from_its_first_day():
    idx = pd.date_range("2021-01-20", "2021-01-24", freq="D", tz="UTC")
    rated = pd.DataFrame({"link": ["L", "L", "M"], "cable": ["a", "b", "c"], "rated_mw": [2000.0, 1000.0, 500.0],
                          "in_service_from": ["2016-01-01", "2021-01-22", "2016-01-01"]})
    s = I.rated_capacity("L", idx, rated)
    assert list(s) == [2000.0, 2000.0, 3000.0, 3000.0, 3000.0]
    with pytest.raises(KeyError, match="N"):
        I.rated_capacity("N", idx, rated)


def test_missing_year_file_is_named(tmp_path, monkeypatch):
    monkeypatch.setattr(I.cfg, "raw_dir", lambda: tmp_path)
    (tmp_path / "entsoe" / "dayahead_prices").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="fr"):
        I.load_price("fr")
