"""The storage positions valued at the day-ahead auction prices (gbpowerdata.build.storage_revenues_dayahead) on
synthetic series: an hourly auction's price applies to both half-hours of its hour, a half-hour without a price is
left out of the value (not valued at zero) and counted in priced_share, and the auctions stay in separate columns.
No data/, no network and no licensed data needed."""
import numpy as np
import pandas as pd
import pytest

from gbpowerdata.build import storage_revenues_dayahead as SD

UTC = "UTC"


def test_a_position_is_valued_at_the_price_of_its_half_hour_and_unpriced_energy_is_counted_apart():
    t = pd.date_range("2024-03-01", periods=4, freq="30min", tz=UTC)
    energy = pd.Series([10.0, -20.0, 5.0, 5.0], index=t)
    hourly = pd.Series([100.0, 100.0, np.nan, np.nan], index=t)          # the second hour has no price
    v = SD.value(energy, hourly).loc["2024-03"]
    assert v["gbp"] == pytest.approx(10 * 100 - 20 * 100)
    assert v["priced_share"] == pytest.approx(30 / 40)


def test_a_month_without_any_price_has_no_value_rather_than_zero():
    t = pd.date_range("2019-06-01", periods=2, freq="30min", tz=UTC)
    v = SD.value(pd.Series([10.0, 10.0], index=t), pd.Series(dtype=float)).loc["2019-06"]
    assert np.isnan(v["gbp"]) and v["priced_share"] == 0.0


def test_every_auction_has_its_own_columns():
    assert set(SD.AUCTIONS) == {"n2ex", "epex_hourly", "epex_hh", "blend"}
    for a in SD.AUCTIONS:
        assert f"wholesale_{a}_gbp" in SD.COLUMNS and f"priced_share_{a}" in SD.COLUMNS
