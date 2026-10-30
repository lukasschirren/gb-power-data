"""The baseload reference price on the half-hourly spine (build.bmrp): each half-hour takes its season's price."""
from __future__ import annotations

import numpy as np
import pandas as pd

from gbpowerdata.build import bmrp as B


def _seasons():
    return pd.DataFrame({"season": ["Winter 2023", "Summer 2024"],
                         "season_start": pd.to_datetime(["2023-10-01", "2024-04-01"], utc=True),
                         "season_end": pd.to_datetime(["2024-03-31", "2024-09-30"], utc=True),
                         "bmrp_gbp_mwh": [110.0, 70.0]})


def test_each_half_hour_takes_its_seasons_price_and_uncovered_hours_are_nan():
    hh = B.to_halfhourly(_seasons(), "2023-09-30", "2024-04-02").set_index("startTime")
    assert np.isnan(hh.loc["2023-09-30 12:00+00:00", "bmrp_gbp_mwh"])
    assert hh.loc["2023-12-01 12:00+00:00", "bmrp_gbp_mwh"] == 110.0
    assert hh.loc["2024-03-31 23:30+00:00", "bmrp_gbp_mwh"] == 110.0      # the season runs to the end of its last day
    assert hh.loc["2024-04-01 00:00+00:00", "bmrp_gbp_mwh"] == 70.0
    assert hh.loc["2024-04-01 00:00+00:00", "season"] == "Summer 2024"
    assert list(hh.columns) == ["season", "bmrp_gbp_mwh"]


def test_the_spine_is_half_hourly_utc_and_ends_at_the_end_instant():
    hh = B.to_halfhourly(_seasons(), "2024-01-01", "2024-01-01 23:30")
    assert len(hh) == 48 and str(hh["startTime"].dt.tz) == "UTC"
    assert len(B.to_halfhourly(_seasons(), "2024-01-01", "2024-01-01")) == 1   # the end date's midnight, as the spine
