"""The ERA5 weather series (build.weather_years): the fleet weighting of GSP-group series on synthetic frames."""
from __future__ import annotations

import pandas as pd
import pytest

from gbpowerdata.build import weather_years as W


def _gsp():
    idx = pd.date_range("2020-01-01", periods=3, freq="h", tz="UTC")
    return pd.DataFrame({"_A_onshore_wind": [0.2, 0.4, 0.6], "_B_onshore_wind": [0.0, 1.0, 1.0],
                         "_A_solar_pv": [0.1, 0.2, 0.3]}, index=idx)


def test_weighted_national_is_the_capacity_weighted_mean_over_groups():
    w = pd.DataFrame({"tech": ["Onshore", "Onshore", "Solar"], "gsp_group": ["_A", "_B", "_A"],
                      "capacity_mw": [300.0, 100.0, 50.0]})
    nat = W.weighted_national(_gsp(), w)
    assert list(nat["wind_onshore_cf"].round(4)) == [0.15, 0.55, 0.7]
    assert list(nat["solar_cf"].round(4)) == [0.1, 0.2, 0.3]
    assert "wind_offshore_cf" not in nat.columns            # no offshore series in the frame


def test_weight_in_a_group_without_a_series_is_renormalised_and_warned():
    w = pd.DataFrame({"tech": ["Onshore", "Onshore", "Solar"], "gsp_group": ["_A", "_Z", "_A"],
                      "capacity_mw": [300.0, 300.0, 50.0]})
    with pytest.warns(UserWarning, match="_Z"):
        nat = W.weighted_national(_gsp(), w)
    assert list(nat["wind_onshore_cf"].round(4)) == [0.2, 0.4, 0.6]
    with pytest.raises(ValueError, match="_Z"):
        W.weighted_national(_gsp(), w, on_missing="raise")


def test_no_weight_on_any_group_with_a_series_raises():
    w = pd.DataFrame({"tech": ["Onshore"], "gsp_group": ["_Z"], "capacity_mw": [300.0]})
    with pytest.raises(ValueError, match="Onshore"):
        W.weighted_national(_gsp(), w, on_missing="ignore")
