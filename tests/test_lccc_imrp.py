"""LCCC's IMRP (gbpowerdata.common.lccc.imrp) on a synthetic file shaped like the portal's "imrp-actuals": each date is
a UK local day whose period p is its p-th hour, 23 or 25 of them on the clock-change days, and each hourly price
applies to both half-hours of its hour; and a position valued at it (storage_revenues.valued_at), where a month
without a price is empty, not zero. No data/ and no network needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import storage_revenues as S
from gbpowerdata.common import lccc

UTC = "UTC"


def _write(tmp_path, rows):
    (tmp_path / "lccc").mkdir()
    pd.DataFrame(rows, columns=["IMRP_Date", "Settlement_Period", "IMRP_Amount"]).to_csv(
        tmp_path / "lccc" / lccc.IMRP_FILE, index=False)


def test_imrp_periods_are_hours_of_the_uk_local_day_on_both_half_hours(tmp_path):
    rows = [("2023-07-01 00:00:00.0000000", "1", "80.5"), ("2023-07-01 00:00:00.0000000", "2", "70.0")]
    rows += [("2023-03-26 00:00:00.0000000", str(p), str(p)) for p in range(1, 24)]     # spring: 23 hours
    rows += [("2023-10-29 00:00:00.0000000", str(p), str(p)) for p in range(1, 26)]     # autumn: 25 hours
    _write(tmp_path, rows)
    s = lccc.imrp(tmp_path)
    assert s[pd.Timestamp("2023-06-30 23:00", tz=UTC)] == 80.5            # 00:00 BST
    assert s[pd.Timestamp("2023-06-30 23:30", tz=UTC)] == 80.5            # the hour's second half-hour
    assert s[pd.Timestamp("2023-07-01 00:00", tz=UTC)] == 70.0
    assert s[pd.Timestamp("2023-03-26 00:00", tz=UTC)] == 1.0 and s[pd.Timestamp("2023-03-26 22:00", tz=UTC)] == 23.0
    assert s[pd.Timestamp("2023-10-28 23:00", tz=UTC)] == 1.0 and s[pd.Timestamp("2023-10-29 23:00", tz=UTC)] == 25.0
    assert not s.index.duplicated().any()


def test_no_imrp_file_gives_an_empty_series(tmp_path):
    assert lccc.imrp(tmp_path).empty


def test_a_position_is_valued_where_priced_and_a_month_without_price_is_empty():
    t = pd.date_range("2024-01-31 23:00", periods=4, freq="30min", tz=UTC)    # two half-hours in each month
    energy = pd.Series([10.0, -5.0, 8.0, 2.0], index=t)
    price = pd.Series([50.0, 50.0], index=t[:2])                           # February has no price
    v = S.valued_at(energy, price)
    assert v["2024-01"] == pytest.approx(10 * 50 - 5 * 50)
    assert np.isnan(v["2024-02"])
