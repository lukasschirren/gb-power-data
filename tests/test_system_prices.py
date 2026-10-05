"""The cash-out table of gbpowerdata.build.build_system_prices on synthetic rows shaped like the
Elexon response: a republished period keeps its latest publication; the published UTC start
times put the 46 periods of a spring clock-change day on the UTC spine with nothing shifted and a
period missing from the pull left empty; the sell/buy split is counted, not assumed away; the
puller's settlement dates stop at today. No data/ and no network needed."""
from datetime import date

import numpy as np
import pandas as pd

from gbpowerdata.build import build_system_prices as B
from gbpowerdata.pull import system_price_pull as P


def _rows(day: str, n: int, start_utc: str, price: float = 50.0, created_min: int = 50) -> pd.DataFrame:
    st = pd.date_range(start_utc, periods=n, freq="30min", tz="UTC")
    return pd.DataFrame({
        "settlementDate": day, "settlementPeriod": np.arange(1, n + 1),
        "startTime": st.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "createdDateTime": (st + pd.Timedelta(minutes=created_min)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "systemSellPrice": price, "systemBuyPrice": price, "netImbalanceVolume": 10.0,
        "reserveScarcityPrice": np.nan, "priceDerivationCode": "N",
        "totalAcceptedOfferVolume": 100.0, "totalAcceptedBidVolume": -40.0,
        "totalAdjustmentSellVolume": 0.0, "totalAdjustmentBuyVolume": 5.0,
    })


def test_republished_period_keeps_the_latest():
    first = _rows("2023-01-01", 48, "2023-01-01T00:00Z", price=50.0)
    again = _rows("2023-01-01", 2, "2023-01-01T00:00Z", price=80.0, created_min=600)
    out = B.to_spine(pd.concat([first, again], ignore_index=True), 2023)
    assert out["price_gbp_per_mwh"].iloc[:3].tolist() == [80.0, 80.0, 50.0]


def test_clock_change_day_lands_on_the_utc_spine():
    # 26 March 2023: 46 periods, 00:00 to 22:30 UTC (the local day ends at 23:00 UTC).
    spring = _rows("2023-03-26", 46, "2023-03-26T00:00Z", price=70.0)
    nxt = _rows("2023-03-27", 48, "2023-03-26T23:00Z", price=90.0)
    out = B.to_spine(pd.concat([spring, nxt], ignore_index=True), 2023)
    assert len(out) == 17520 and out.index.is_monotonic_increasing
    day = out.loc["2023-03-26"]
    assert day["price_gbp_per_mwh"].iloc[:46].eq(70.0).all()      # 00:00 .. 22:30
    assert day["price_gbp_per_mwh"].iloc[46:].eq(90.0).all()      # 23:00, 23:30 belong to the 27th
    assert out.loc["2023-03-25", "price_gbp_per_mwh"].isna().all()   # not pulled: empty, not filled


def test_columns_and_signs_are_as_published():
    out = B.to_spine(_rows("2023-01-01", 48, "2023-01-01T00:00Z"), 2023)
    assert list(out.columns) == list(B.COLUMNS.values())
    row = out.iloc[0]
    assert row["niv_mwh"] == 10.0 and row["accepted_offer_mwh"] == 100.0 and row["accepted_bid_mwh"] == -40.0
    assert row["price_derivation_code"] == "N" and np.isnan(row["reserve_scarcity_price_gbp_per_mwh"])


def test_price_split_counts_differences():
    d = _rows("2023-01-01", 48, "2023-01-01T00:00Z")
    assert B.price_split(B.latest(d)) == 0
    d.loc[[3, 7], "systemSellPrice"] = 49.0
    assert B.price_split(B.latest(d)) == 2


def test_settlement_dates_stop_at_today():
    assert len(P.settlement_dates(2024, date(2026, 1, 1))) == 366          # a leap year, complete
    part = P.settlement_dates(2026, date(2026, 1, 10))
    assert part[0] == date(2026, 1, 1) and part[-1] == date(2026, 1, 10)
    assert P.settlement_dates(2027, date(2026, 1, 10)) == []               # nothing published yet
