"""The official totals the built tables are reconciled with: data/reference/official_statistics.csv.

Each row is one statistic for one year (calendar, financial year starting April, or end of year) and scope (UK or
GB), with its publisher, URL, locator (sheet and cell, or the quoted sentence), licence and status: `verified` where
the value was read from the source by hand, `to verify` where it was not. Only verified rows are used by default.
The scope matters: DESNZ's totals are for the UK, the panel's for GB (Northern Ireland, about 2.5% of UK demand, is
outside the GB system), so a comparison is of levels within a band or of changes between years, never of equality.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

FILE = "official_statistics.csv"


def load(verified_only: bool = True, path: Path | None = None) -> pd.DataFrame:
    p = cfg.reference_dir() / FILE if path is None else Path(path)
    t = pd.read_csv(p)
    return t[t["status"] == "verified"].reset_index(drop=True) if verified_only else t


def series(stat: str, table: pd.DataFrame | None = None) -> pd.Series:
    """One statistic by year (float values), from `table` or the verified rows."""
    t = load() if table is None else table
    s = t[t["stat"] == stat]
    return pd.Series(s["value"].astype(float).to_numpy(), index=s["year"].astype(int).to_numpy(), name=stat).sort_index()
