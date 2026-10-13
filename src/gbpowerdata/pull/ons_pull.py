"""Pull time series from the Office for National Statistics into data/raw/ons/.

Why: Capacity Market payments of the T-4 (and T-3) auctions are indexed to the UK Consumer Prices Index (The
Electricity Capacity Regulations 2014, SI 2014/2043, Schedule 1 paragraph 3(5): the clearing price x CPI_x / CPI_base,
each the mean of the monthly CPI values over a winter, 1 October to 30 April), so gbpowerdata.build.capacity_market
needs the monthly index. The regulations name it: "the UK Consumer Prices Index (All Items) published monthly by the
Office for National Statistics" (regulation 2).

Source: the ONS website's time series API, https://www.ons.gov.uk/{topic}/timeseries/{series}/{dataset}/data (JSON,
no key). Series pulled (SERIES):
  d7bt / mm23   CPI INDEX 00: ALL ITEMS 2015=100, monthly from Jan 1988 (Consumer price inflation dataset MM23)
Licence: Open Government Licence v3.0 (the ONS site: "All content is available under the Open Government Licence
v3.0, except where otherwise stated"; checked 10 Oct 2026).

Gotchas: the index is published to one decimal place, about mid-way through the next month (Aug 2026 on 16 Sep
2026). The whole series is rewritten on every run.

Output: data/raw/ons/cpi_index_d7bt.csv: month (first day, YYYY-MM-DD), value, update_date.
Read it with gbpowerdata.common.ons.cpi_index().

Usage: python -m gbpowerdata.pull.ons_pull
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd
import requests

from gbpowerdata import config as cfg

BASE = "https://www.ons.gov.uk"
# series id -> (topic path, dataset, output stem)
SERIES = {"d7bt": ("economy/inflationandpriceindices", "mm23", "cpi_index_d7bt")}


def out_dir():
    return cfg.raw_dir() / "ons"


def monthly(payload: dict) -> pd.DataFrame:
    """The monthly observations of an ONS time series JSON: month, value, update_date (empty values dropped)."""
    m = pd.DataFrame(payload.get("months") or [])
    if m.empty:
        return pd.DataFrame(columns=["month", "value", "update_date"])
    m = m[m["value"].astype(str).str.strip() != ""]
    return pd.DataFrame({"month": pd.to_datetime(m["date"], format="%Y %b").dt.strftime("%Y-%m-%d"),
                         "value": pd.to_numeric(m["value"]),
                         "update_date": m.get("updateDate", "")}).reset_index(drop=True)


def pull(series: str = "d7bt") -> str:
    topic, dataset, stem = SERIES[series]
    r = requests.get(f"{BASE}/{topic}/timeseries/{series}/{dataset}/data", timeout=120)
    r.raise_for_status()
    payload = r.json()
    table = monthly(payload)
    if table.empty:
        raise RuntimeError(f"ons_pull: no monthly values for {series}/{dataset}")
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{stem}.csv"
    table.to_csv(path, index=False)
    print(f"  {payload['description']['title']}: {len(table):,} months to {table['month'].iat[-1]} -> {path}")
    return str(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("series", nargs="*", default=list(SERIES), help=f"series ids (default: {', '.join(SERIES)})")
    a = ap.parse_args(argv)
    for s in a.series:
        pull(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
