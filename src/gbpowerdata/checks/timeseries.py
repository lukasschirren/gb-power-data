"""The half-hourly UTC spine every time series of the panel shares.

Each table holds one row per half-hour of the calendar year in UTC (17,520 rows, 17,568 in a leap year), keyed on
`startTime`. In UK local time that spine has 46 settlement periods on the day the clocks go forward and 50 on the day
they go back; Elexon numbers a settlement period from 1 at local midnight, so its UTC start is local midnight plus
30 minutes per period before it.
"""
from __future__ import annotations

import calendar

import pandas as pd

LOCAL = "Europe/London"


def expected_rows(year: int) -> int:
    return 17568 if calendar.isleap(year) else 17520


def spine(df: pd.DataFrame, year: int, col: str = "startTime", keys: list[str] | None = None) -> dict:
    """rows, distinct times, times missing from and extra to the year's UTC spine, rows off the half-hour grid, and
    duplicate rows (on the time, or on the time and `keys` for a long table)."""
    t = pd.to_datetime(df[col], utc=True)
    grid = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="30min", tz="UTC", inclusive="left")
    have = pd.DatetimeIndex(t.unique())
    return {"rows": len(df), "times": len(have), "expected": expected_rows(year),
            "missing": len(grid.difference(have)), "extra": len(have.difference(grid)),
            "off_grid": int(((t.dt.minute % 30) != 0).sum() + (t.dt.second != 0).sum()),
            "duplicates": int(df.assign(_t=t).duplicated(["_t", *(keys or [])]).sum())}


def local_day_periods(times: pd.Series) -> pd.Series:
    """Settlement periods per UK local day of a set of UTC half-hour starts (index: the date)."""
    return pd.to_datetime(times, utc=True).dt.tz_convert(LOCAL).dt.date.value_counts().sort_index()


def clock_change_days(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The UK local dates the clocks go forward (46 periods) and back (50 periods) in `year`."""
    days = pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D")
    n = [len(pd.date_range(d.tz_localize(LOCAL), (d + pd.Timedelta(days=1)).tz_localize(LOCAL), freq="30min",
                           inclusive="left")) for d in days]
    s = pd.Series(n, index=days)
    return s[s == 46].index[0], s[s == 50].index[0]


def settlement_start(settlement_date: pd.Series, period: pd.Series) -> pd.Series:
    """The UTC start of settlement period `period` of UK settlement day `settlement_date`."""
    day = pd.to_datetime(settlement_date.astype(str).str[:10]).dt.tz_localize(LOCAL)
    return day.dt.tz_convert("UTC") + pd.to_timedelta((period.astype(int) - 1) * 30, unit="min")
