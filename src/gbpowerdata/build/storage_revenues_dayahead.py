"""The storage units' notified positions valued at the GB day-ahead auction prices, by unit and month
-> data/processed/storage_revenue_dayahead_{year}.csv (LICENSED: local only, never committed or packed).

Why: storage_revenue_{y} values each unit's notified position at Elexon's market index (MID), the volume-weighted
price of the half-hour's short-term trades, because that price is public. A unit's final position is the net of
what it traded day-ahead and intraday, so the MID is one estimate of its value among several, and indices that
value the position at the day-ahead auctions instead (a commercial index does so by its published methodology)
come out at another level. This table measures that choice from the licensed auction prices (a Nord Pool or EPEX
SPOT subscription), so the open table's caveat can say how much it matters. Nothing here changes the open table.

Method, per unit and month of storage_revenue_{y} that has notifications (has_fpn):
  energy       the notified energy per half-hour (common.elexon.fpn_energy; discharging positive).
  prices       each auction on its own, never mixed in one series (gbpowerdata.venue): N2EX (hourly), EPEX SPOT GB
               hourly and the volume-weighted N2EX/EPEX hourly blend, each hourly price on both half-hours of its
               hour; EPEX SPOT GB half-hourly (15:30 auction) on its own half-hour. The hourly auctions sell the
               hour as one product, so an hourly price on a half-hour is that product's price, not an estimate of
               a half-hourly one.
  value        wholesale_{auction}_gbp = sum of energy x price over the half-hours the auction priced;
               priced_share_{auction} = the share of the month's moved energy (|MWh|) it priced (EPEX has no prices
               before 2020; a half-hour without a price is left out, not valued at zero).
  wholesale_mid_gbp is storage_revenue_{y}'s wholesale_gbp, for the comparison.
Gaps: the same as storage_revenue_{y}'s for the position (fpn_coverage, docs/storage_revenues.md); the day-ahead
price is the auction's clearing price, so this assumes the whole final position traded in that auction.

Inputs: data/processed/storage_revenue_{y}.csv (gbpowerdata.build.storage_revenues), data/raw/fpn/{unit}.csv, and
data/processed/dayahead_price_{n2ex,epex_hourly,epex_hh,blend}_{y}.csv (gbpowerdata.build.build_dayahead_prices).
Output: one row per unit and month: year, month, unit_id, tech, capacity_mw, discharge_mwh, charge_mwh,
fpn_coverage, wholesale_mid_gbp, wholesale_{n2ex,epex_hourly,epex_hh,blend}_gbp,
priced_share_{n2ex,epex_hourly,epex_hh,blend}. The file name carries "dayahead", which .gitignore,
tests/test_repo_hygiene.py and the data pack's licensed-data guard all refuse.

Usage: python -m gbpowerdata.build.storage_revenues_dayahead [--years 2018 2025]
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata import venue

# output label -> venue key (gbpowerdata.venue.REGISTRY)
AUCTIONS = {"n2ex": "n2ex", "epex_hourly": "epex", "epex_hh": "epex_hh", "blend": "blend"}
KEYS = ["year", "month", "unit_id", "tech", "capacity_mw", "discharge_mwh", "charge_mwh", "fpn_coverage"]
COLUMNS = (KEYS + ["wholesale_mid_gbp"] + [f"wholesale_{a}_gbp" for a in AUCTIONS]
           + [f"priced_share_{a}" for a in AUCTIONS])


def value(energy: pd.Series, price: pd.Series) -> pd.DataFrame:
    """Per month (YYYY-MM): the energy valued at `price` over the half-hours it priced, and the priced share of the
    moved energy. Both series are indexed by the UTC start of the half-hour."""
    p = price.reindex(energy.index)
    has = p.notna()
    month = energy.index.strftime("%Y-%m")
    gbp = (energy * p).where(has, 0.0).groupby(month).sum()
    moved = energy.abs().groupby(month).sum()
    priced = energy.abs().where(has, 0.0).groupby(month).sum()
    return pd.DataFrame({"gbp": gbp.where(priced > 0), "priced_share": (priced / moved.where(moved > 0)).fillna(0.0)})


def prices(year: int) -> dict[str, pd.Series]:
    """Each auction's day-ahead price for `year` on the half-hourly UTC spine (empty where it has none)."""
    return {a: venue.get(key).load_da_price(year) for a, key in AUCTIONS.items()}


def build_year(year: int) -> pd.DataFrame:
    from gbpowerdata.build import storage_revenues as S

    path = cfg.processed_dir() / f"storage_revenue_{year}.csv"
    if not path.exists():
        raise SystemExit(f"{path.name} is missing: run python -m gbpowerdata.build.storage_revenues first")
    t = pd.read_csv(path)
    t = t[t["has_fpn"].astype(bool)].copy()
    if "fpn_coverage" not in t:
        t["fpn_coverage"] = np.nan
    px = prices(year)
    lo, hi = pd.Timestamp(f"{year}-01-01", tz="UTC"), pd.Timestamp(f"{year + 1}-01-01", tz="UTC")
    parts = []
    for unit, rows in t.groupby("unit_id"):
        f = cfg.raw_dir() / "fpn" / f"{unit}.csv"
        if not f.exists():
            continue
        e = S.fpn_energy(f)
        e = e[(e.index >= lo) & (e.index < hi)]
        out = rows[KEYS].assign(wholesale_mid_gbp=rows["wholesale_gbp"].to_numpy()).set_index("month", drop=False)
        for a, p in px.items():
            v = value(e, p) if len(p) else pd.DataFrame({"gbp": pd.Series(dtype=float),
                                                          "priced_share": pd.Series(dtype=float)})
            out[f"wholesale_{a}_gbp"] = v["gbp"].reindex(out.index)
            out[f"priced_share_{a}"] = v["priced_share"].reindex(out.index).fillna(0.0)
        parts.append(out.reset_index(drop=True))
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(parts, ignore_index=True)[COLUMNS].sort_values(["month", "unit_id"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--years", nargs=2, type=int, default=[2018, 2025])
    a = ap.parse_args(argv)
    for y in range(a.years[0], a.years[1] + 1):
        d = build_year(y)
        out = cfg.processed_dir() / f"storage_revenue_dayahead_{y}.csv"
        d.to_csv(out, index=False)
        b = d[d["tech"] == "battery"]
        tot = {c.removeprefix("wholesale_").removesuffix("_gbp"): round(b[c].sum() / 1e6, 2)
               for c in d.columns if c.startswith("wholesale_")}
        print(f"  {out.name}: {d['unit_id'].nunique()} units; batteries' wholesale GBP m {tot}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
