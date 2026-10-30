"""The metered wind split (build.vre_split): the reanalysis share and the fleet capacity factor, on synthetic data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gbpowerdata.build import vre_split as V


def test_offshore_share_weights_the_two_shapes_by_capacity():
    share = V.offshore_share(np.array([0.5, 0.0, 0.0]), np.array([0.5, 0.5, 0.0]), cap_off=1000.0, cap_ons_t=1000.0)
    assert share[0] == 0.5          # equal capacity, equal CF: half
    assert share[1] == 0.0          # offshore still, onshore blowing: nothing offshore
    assert share[2] == 0.5          # both still: the capacity share


def test_offshore_share_without_transmission_onshore_is_one():
    share = V.offshore_share(np.array([0.3, 0.0]), np.array([0.9, 0.9]), cap_off=1000.0, cap_ons_t=0.0)
    assert list(share) == [1.0, 1.0]


def test_ninja_fleet_cf_is_the_capacity_weighted_mean_of_the_groups(tmp_path):
    t = pd.date_range("2023-01-01", periods=2, freq="h", tz="UTC")
    for grp, cf in (("A", [0.2, 0.4]), ("B", [1.0, 0.0])):
        pd.DataFrame({"time": t.strftime("%Y-%m-%d %H:%M:%S+00:00"), "cf": cf}).to_csv(
            tmp_path / f"offshore__{grp}_2023.csv", index=False)
    s = V.ninja_fleet_cf("offshore", 2023, pd.Series({"_A": 300.0, "_B": 100.0}), ninja_dir=tmp_path)
    assert list(s.round(4)) == [0.4, 0.3]
    unweighted = V.ninja_fleet_cf("offshore", 2023, None, ninja_dir=tmp_path)
    assert list(unweighted.round(4)) == [0.6, 0.2]


def test_ninja_fleet_cf_is_empty_without_files(tmp_path):
    assert V.ninja_fleet_cf("onshore", 2023, None, ninja_dir=tmp_path).empty
