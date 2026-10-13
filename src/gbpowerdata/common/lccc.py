"""Readers of the Low Carbon Contracts Company's open data (data/raw/lccc/, gbpowerdata.pull.lccc_pull) that more than
one stage needs.

imrp(): the Intermittent Market Reference Price, LCCC data portal dataset "imrp-actuals" (Open Government Licence
v3.0, updated daily, hourly from 30 Jun 2016): the GB day-ahead hourly price intermittent CfDs are settled against.
From 1 Jan 2021 it is the average of the N2EX and EPEX SPOT GB hourly day-ahead auction prices weighted by the volume
each traded (LCCC, "How the Intermittent Market Reference Price will be calculated from 1 January 2021"; CfD standard
terms, Condition 21.2); before, the two auctions cleared one coupled price and the IMRP is that price. Each
IMRP_Date is a UK local day and Settlement_Period p its p-th hour (23 or 25 of them on the clock-change days): read
so, the IMRP of the coupled years 2019-2020 equals the auction price it is computed from in nearly every hour, read
with the day starting at midnight CET in almost none (checked locally against the licensed prices, 10 Oct 2026).
Each hourly price applies to both half-hours of its hour. LCCC publishes it under the OGL, so the IMRP, and a table
priced at it, may be shared and packed, unlike the auction prices it is computed from.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

IMRP_FILE = "imrp_actuals.csv"


def imrp(raw: Path | None = None) -> pd.Series:
    """The IMRP (GBP/MWh) on the half-hourly UTC spine, from data/raw/lccc/imrp_actuals.csv; empty if not pulled
    (python -m gbpowerdata.pull.lccc_pull imrp-actuals)."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    path = raw / "lccc" / IMRP_FILE
    if not path.exists():
        return pd.Series(dtype=float, name="imrp_gbp_per_mwh")
    d = pd.read_csv(path, usecols=["IMRP_Date", "Settlement_Period", "IMRP_Amount"])
    day = pd.to_datetime(d["IMRP_Date"].astype(str).str[:10])
    start = (day.dt.tz_localize("Europe/London").dt.tz_convert("UTC")
             + pd.to_timedelta(pd.to_numeric(d["Settlement_Period"]).astype(int) - 1, unit="h"))
    hourly = pd.Series(pd.to_numeric(d["IMRP_Amount"], errors="coerce").to_numpy(), index=start).dropna()
    hourly = hourly[~hourly.index.duplicated(keep="last")].sort_index()
    half = pd.concat([hourly, hourly.set_axis(hourly.index + pd.Timedelta(minutes=30))]).sort_index()
    return half[~half.index.duplicated()].rename("imrp_gbp_per_mwh")
