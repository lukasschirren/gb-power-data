"""The daily GB gas price, one row per gas day from 1 January 2018 -> data/processed/gas_sap_daily.csv.

WHY. The half-hourly panels carry the gas price on each half-hour of a calendar year (fuel_prices_{year}.csv, stage
2), which suits a model clearing a year but not one fitting the price's own dynamics. A model of the gas price's
day-to-day movements (gb-power-model's projection, through the library gas-price-paths) needs the daily series as it
is published, without the calendar-year split, and up to the latest published day rather than the end of the panel's
last full year.

SOURCE. The ONS System Average Price (SAP) of gas, pulled by gbpowerdata.pull.gas_pull into
data/raw/gas_sap_daily.csv from ONS's dated editions (that module's docstring, EDITIONS):
https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas, Open
Government Licence v3.0 (datapack source "govuk"). SAP is the weighted average price of the On-the-Day Commodity
Market's trades, in pence per kWh of gas on the gross calorific basis (gas_pull's docstring); the table carries it
in pence per kWh and in pence per therm (29.3071 kWh a therm), nominal.

METHOD. The raw series is kept from 2018-01-01. A repeated date or a price that is not positive stops the build,
since either would be a pull error. A day missing between the first and the last is reported and left missing (no
row): a model reads it as a missing observation, which is better than a filled value. The values are those of the
raw file, unchanged, so the table's days up to 2025-12-31 equal the gas price of fuel_prices_2018-2025.

OUTPUT data/processed/gas_sap_daily.csv   date (YYYY-MM-DD), gas_price_pence_per_kwh, gas_price_pence_per_therm
RUN    python -m gbpowerdata.build.gas_sap_daily          (after python -m gbpowerdata.pull.gas_pull)
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from gbpowerdata import config as cfg

FIRST = "2018-01-01"
RAW = "gas_sap_daily.csv"
OUT = "gas_sap_daily.csv"
COLUMNS = ["date", "gas_price_pence_per_kwh", "gas_price_pence_per_therm"]


def build(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """(the table, the missing days as YYYY-MM-DD) from the raw series (docstring, METHOD)."""
    d = raw[COLUMNS].copy()
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d = d[d["date"] >= FIRST].sort_values("date").reset_index(drop=True)
    rep = d["date"][d["date"].duplicated()]
    if len(rep):
        raise SystemExit(f"gas_sap_daily: the raw series repeats {sorted(set(rep))[:5]}")
    bad = d[~(d["gas_price_pence_per_therm"] > 0) | ~(d["gas_price_pence_per_kwh"] > 0)]
    if len(bad):
        raise SystemExit(f"gas_sap_daily: prices must be positive; not on {bad['date'].tolist()[:5]}")
    days = pd.date_range(d["date"].iloc[0], d["date"].iloc[-1], freq="D").strftime("%Y-%m-%d")
    gaps = sorted(set(days) - set(d["date"]))
    return d, gaps


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args(argv)
    raw = pd.read_csv(cfg.raw_dir() / RAW)
    table, gaps = build(raw)
    out = cfg.processed_dir() / OUT
    table.to_csv(out, index=False)
    print(f"gas_sap_daily: {len(table)} days {table['date'].iloc[0]} -> {table['date'].iloc[-1]} -> {out}")
    if gaps:
        print(f"  {len(gaps)} missing days left missing: {gaps[:10]}{' ...' if len(gaps) > 10 else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
