"""Cash-out price and net imbalance volume per settlement period on the half-hourly UTC spine.

Why: the imbalance (cash-out) price is what a party is paid or pays for the energy it did not
trade, so it is the outside option behind every intraday price; the net imbalance volume says
whether the system was short or long in the period. Neither was in the processed layer.

Source (gbpowerdata.pull.system_price_pull):
  data/raw/system_prices/system_prices_{year}.csv   one row per settlement period as published on
                                                    BMRS, with its UTC startTime

Method:
  - A period published more than once keeps its latest createdDateTime.
  - The published startTime is already UTC, so the clock-change days (46 and 50 periods) fall on
    the spine without a local-time conversion; a period missing from the pull stays empty.
  - One price: since BSC modification P305 (5 November 2015) the system sell and buy prices are
    equal. The build counts the periods where they differ and prints the count; it does not
    assume it is zero. `price_gbp_per_mwh` is the buy price.
  - Volumes are MWh in the period, signs as published: accepted offers positive, accepted bids
    negative; net imbalance volume positive when the system was short.

Gotchas: P305 changed the price twice. From 5 November 2015 the price is the volume-weighted
average of the most expensive 50 MWh of actions (PAR 50) and the value of lost load in the
reserve scarcity price is GBP 3,000/MWh; from 1 November 2018 it is the most expensive 1 MWh
(PAR 1) and GBP 6,000/MWh. Do not pool price levels across that date without saying so. The
reserve scarcity price is empty in most periods (it is published only when a scarcity price
was calculated).

Output: data/processed/system_prices_{year}.csv, half-hourly UTC `startTime` (the calendar year
in UTC), columns price_gbp_per_mwh, niv_mwh, reserve_scarcity_price_gbp_per_mwh,
price_derivation_code, accepted_offer_mwh, accepted_bid_mwh, adjustment_sell_mwh,
adjustment_buy_mwh.
Read it with gbpowerdata.processed.read_system_prices(year) (half-hourly) or
read_system_prices(year, hourly=True) (the hourly product: mean price, summed volumes).

Usage: python -m gbpowerdata.build.build_system_prices [--years 2016 2025]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from gbpowerdata import config as cfg

COLUMNS = {
    "systemBuyPrice": "price_gbp_per_mwh",
    "netImbalanceVolume": "niv_mwh",
    "reserveScarcityPrice": "reserve_scarcity_price_gbp_per_mwh",
    "priceDerivationCode": "price_derivation_code",
    "totalAcceptedOfferVolume": "accepted_offer_mwh",
    "totalAcceptedBidVolume": "accepted_bid_mwh",
    "totalAdjustmentSellVolume": "adjustment_sell_mwh",
    "totalAdjustmentBuyVolume": "adjustment_buy_mwh",
}
PRICE_TOL = 1e-6      # GBP/MWh: sell and buy price count as different above this


def spine(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="30min", tz="UTC", inclusive="left", name="startTime")


def latest(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per settlement period (UTC `startTime` index): the latest publication."""
    d = raw.copy()
    d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
    d["createdDateTime"] = pd.to_datetime(d["createdDateTime"], utc=True)
    d = d.sort_values(["startTime", "createdDateTime"]).drop_duplicates("startTime", keep="last")
    return d.set_index("startTime")


def price_split(d: pd.DataFrame) -> int:
    """Number of periods whose system sell price differs from the buy price."""
    both = d[["systemSellPrice", "systemBuyPrice"]].dropna()
    return int(((both["systemSellPrice"] - both["systemBuyPrice"]).abs() > PRICE_TOL).sum())


def to_spine(raw: pd.DataFrame, year: int) -> pd.DataFrame:
    """The raw rows of one year -> the processed table on the year's half-hourly UTC spine."""
    d = latest(raw)
    out = d[[c for c in COLUMNS if c in d.columns]].rename(columns=COLUMNS)
    return out.reindex(spine(year))


def build(year: int) -> pd.DataFrame:
    fp_raw = cfg.raw_dir() / "system_prices" / f"system_prices_{year}.csv"
    raw = pd.read_csv(fp_raw)
    out = to_spine(raw, year)
    fp = cfg.processed_dir() / f"system_prices_{year}.csv"
    out.to_csv(fp, float_format="%.6g")
    cov = out[["price_gbp_per_mwh", "niv_mwh"]].notna().mean().round(4).to_dict()
    short = float((out["niv_mwh"] > 0).mean())
    print(f"[{year}] -> {fp.name}  coverage {cov}  sell != buy in {price_split(latest(raw))} periods  "
          f"mean price {out['price_gbp_per_mwh'].mean():.1f}  system short {short:.1%} of periods", flush=True)
    return out


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", nargs=2, type=int, default=[2016, 2025])
    a = p.parse_args(argv)
    for y in range(a.years[0], a.years[1] + 1):
        build(y)


if __name__ == "__main__":
    main(sys.argv[1:])
