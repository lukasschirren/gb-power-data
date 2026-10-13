"""Readers of Elexon's raw pulls that more than one stage needs, so each rule lives in one place.

market_index(): Elexon's Market Index Data from the APX/EPEX SPOT data provider (data/raw/mid_apx_*.csv,
gbpowerdata.pull.elexon_pull mid): the volume-weighted price and the volume of the half-hour's short-term trades
on the exchange. By the Market Index Definition Statement (v9.0, effective 18 Apr 2019 under BSC modification
P377, https://bscdocs.elexon.co.uk/category-3-documents/market-index-definition-statement) only half-hour and 1, 2
and 4 hour block trades in the weighted time bands count, and the day-ahead auction has weight 0; P377 moved the
window to include trades up to the start of the period and to drop those more than 8 hours ahead, a break in the
series. A settlement period whose qualifying volume is below the 25 MWh liquidity threshold is published with volume
0 AND price 0 (BSC Section T: "deemed to be zero"; 191 half-hours in 2018-2025: 28, 64, 5, 50, 18, 15, 0 and 11 a
year), so a zero-volume price is not a price of GBP 0/MWh but no price at all; mid_prices() drops those periods.
Elexon's API has no row at all for 2,312 periods of 2018-2025 (252, 290, 1,062, 695, 7, 5, 1 and 0 a year; 35
whole UK days and parts of 97 others). Pulls overlapping in time are deduplicated on the period's UTC start, the
latest file winning.

fpn_energy(): a unit's final physical notifications (data/raw/fpn/{unit}.csv, gbpowerdata.pull.fpn_pull) as energy per
half-hour, for the storage revenues (gbpowerdata.build.storage_revenues) and the thermal units' run and down times
(gbpowerdata.build.unit_runs).

Source and terms: Elexon Insights Solution, BMRS data under Elexon's BMRS data licence (datapack SOURCES["elexon"]).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

MAX_SEGMENT_H = 0.5 + 1e-9        # a notification segment lies within its half-hour


def market_index(raw: Path | None = None) -> pd.DataFrame:
    """APX/EPEX SPOT Market Index Data per half-hour (UTC `startTime` index): price (GBP/MWh) and volume (MWh), as
    published, from every mid_apx_*.csv pull."""
    raw = cfg.raw_dir() if raw is None else Path(raw)
    files = sorted(raw.glob("mid_apx_*.csv"))
    if not files:
        raise FileNotFoundError(f"no mid_apx_*.csv in {raw}: run python -m gbpowerdata.pull.elexon_pull mid")
    m = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    m = m[m["dataProvider"].astype(str).str.upper().str.startswith("APX")].copy()
    m["startTime"] = pd.to_datetime(m["startTime"], utc=True)
    return (m.drop_duplicates("startTime", keep="last").set_index("startTime")[["price", "volume"]]
            .astype(float).sort_index())


def mid_prices(raw: Path | None = None) -> pd.Series:
    """The market index price of every half-hour that had traded volume (periods without trades are left out)."""
    m = market_index(raw)
    return m.loc[m["volume"] > 0, "price"]


def fpn_energy(path: Path) -> pd.Series:
    """A unit's notified energy per half-hour (MWh, signed: export positive), indexed by the UTC start of the
    settlement period: each segment's mean level x its duration, summed over the period's segments."""
    t = pd.read_csv(path, usecols=["timeFrom", "timeTo", "levelFrom", "levelTo"])
    t = t.drop_duplicates(["timeFrom", "timeTo"], keep="last")
    t0 = pd.to_datetime(t["timeFrom"], utc=True)
    t1 = pd.to_datetime(t["timeTo"], utc=True)
    hours = (t1 - t0).dt.total_seconds() / 3600
    if (hours > MAX_SEGMENT_H).any() or (hours < 0).any():
        raise AssertionError(f"fpn_energy: {Path(path).name}: a notification segment outside its half-hour")
    mwh = (t["levelFrom"].astype(float) + t["levelTo"].astype(float)) / 2 * hours
    return mwh.groupby(t0.dt.floor("30min")).sum().rename_axis("startTime")
