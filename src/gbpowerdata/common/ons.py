"""Readers of the Office for National Statistics series (data/raw/ons/, gbpowerdata.pull.ons_pull) that more than one
stage needs.

cpi_index(): the monthly UK Consumer Prices Index, CPI INDEX 00: ALL ITEMS 2015=100 (series D7BT, dataset MM23; Open
Government Licence v3.0), indexed by the first day of each month. The Capacity Market indexes its T-4 clearing prices
to it (gbpowerdata.build.capacity_market); winter_mean() is the mean over a winter as the Electricity Capacity
Regulations 2014 define one (1 October to the following 30 April, regulation 2).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

CPI_FILE = "cpi_index_d7bt.csv"


def cpi_index(raw: Path | None = None) -> pd.Series:
    """Monthly CPI (2015=100) by month start; FileNotFoundError without the pulled file."""
    path = (cfg.raw_dir() if raw is None else Path(raw)) / "ons" / CPI_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `python -m gbpowerdata.pull.ons_pull`")
    t = pd.read_csv(path)
    return pd.Series(t["value"].astype(float).values, index=pd.to_datetime(t["month"]), name="cpi").sort_index()


def winter_mean(cpi: pd.Series, start_year: int) -> float:
    """The mean of the monthly values from October `start_year` to April `start_year` + 1; NaN unless all seven are
    published."""
    w = cpi[pd.Timestamp(start_year, 10, 1): pd.Timestamp(start_year + 1, 4, 1)]
    return float(w.mean()) if len(w) == 7 else float("nan")
