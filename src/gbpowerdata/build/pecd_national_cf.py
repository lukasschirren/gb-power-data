"""Collapse the PECD NUTS-2 wide capacity factors to ONE national series per tech -- the shape
`meritorder` actually reads (`src/meritorder/fundamentals.py:42-44`'s `merge_drivers` ->
`gbpowerdata.processed.load_year`'s `cf` kind -> `capacity_factors_{year}.csv`, columns
`wind_offshore_cf`, `wind_onshore_cf`, `solar_cf`, half-hourly UTC).

Two-step reduction, both capacity-weighted (never a plain average -- a GB-wide CF is the
capacity-weighted mean of its regional CFs, not the unweighted mean across however many regions
happen to exist):
  1. NUTS-2 -> gsp_group via `gbpowerdata.common.pecd_regions.reweight_wide` (area-weight table).
  2. gsp_group -> national using capacity weights from `agents_{year}.csv`, computed the same way
     `stage2b_zone_cf._zone_capacities()` does (same tech/is_offshore selectors) but parametrised
     by year here, since that function is bound to a single YEAR read from config.yaml at import
     time -- so a PECD-driven national CF and the ninja-driven one are capacity-weighted the same
     way, and the only thing that differs between `capacity_factors_{year}.csv` and this file is
     the underlying weather source.

For a year with no matching `agents_{year}.csv` (PECD's own range can run outside the ABM's
2018-2025 panel), the nearest available panel year's capacity mix is used and printed -- a
documented convention, not a silent guess.

Usage:
  python -m gbpowerdata.build.pecd_national_cf                  # every year present in cf_historical.csv
  python -m gbpowerdata.build.pecd_national_cf --years 2023 2023
Output:
  data/processed/capacity_factors_pecd_{year}.csv   (same schema as capacity_factors_{year}.csv)
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import pecd_regions

CFG = cfg.load_config()
RES = int(CFG["resolution_minutes"])
PROC_DIR = cfg.processed_dir()
PECD_DIR = PROC_DIR / "pecd"

# Same three-tech spec as stage2b_zone_cf.TECHS (agents_{year}.csv's tech/is_offshore selectors),
# keyed by this module's PECD column-suffix and the national column name
# capacity_factors_{year}.csv already uses for that tech -- kept as a local, year-parametrised
# copy rather than importing stage2b_zone_cf's private `_zone_capacities()`, which is bound to a
# single YEAR read from config.yaml at import time and can't be reused for an arbitrary year.
TECH_MAP = {
    "offshore_wind": {"national_col": "wind_offshore_cf", "agent_tech": "Wind", "offshore": True},
    "onshore_wind": {"national_col": "wind_onshore_cf", "agent_tech": "Wind", "offshore": False},
    "solar_pv": {"national_col": "solar_cf", "agent_tech": "Solar", "offshore": False},
}


def to_gsp_group_wide(cf_wide: pd.DataFrame) -> pd.DataFrame:
    weights = pecd_regions.nuts2_gsp_group_weights()
    parts = []
    for pecd_tech in TECH_MAP:
        cols = [c for c in cf_wide.columns if c.endswith(f"_{pecd_tech}")]
        if not cols:
            continue
        parts.append(pecd_regions.reweight_wide(cf_wide[cols], weights, "nuts2", pecd_tech))
    if not parts:
        sys.exit("cf_historical.csv has none of the expected tech columns; run pecd_build first.")
    return pd.concat(parts, axis=1)


_agents_year_fallback_notes: set[int] = set()  # resolved fallback years already announced


def _agents_year(year: int) -> int:
    available = sorted(int(p.stem.split("_")[-1]) for p in PROC_DIR.glob("agents_[0-9][0-9][0-9][0-9].csv"))
    if not available:
        sys.exit("No agents_{year}.csv found; run stage3_build_agents first.")
    if year in available:
        return year
    nearest = min(available, key=lambda y: abs(y - year))
    if nearest not in _agents_year_fallback_notes:
        # A wide range of requested years (e.g. a projection ensemble, 2015-2100) all resolve to
        # the SAME nearest panel year once outside 2018-2025 -- announce each resolved fallback
        # year once, not once per requested year, or an 86-year run drowns in identical notes.
        print(f"  note: year(s) outside the agents_{{year}}.csv panel use {nearest}'s capacity "
              f"mix for national weighting")
        _agents_year_fallback_notes.add(nearest)
    return nearest


def _zone_capacities_for_year(year: int) -> pd.DataFrame:
    """Capacity (MW) per (pecd_tech, gsp_group) from agents_{agents_year}.csv -- same selectors
    as `stage2b_zone_cf._zone_capacities()`, parametrised by year rather than the module-level
    config YEAR."""
    a = pd.read_csv(PROC_DIR / f"agents_{_agents_year(year)}.csv")
    rows = []
    for pecd_tech, spec in TECH_MAP.items():
        m = a["tech"] == spec["agent_tech"]
        if spec["agent_tech"] == "Wind":
            m &= a["is_offshore"].astype(bool) == spec["offshore"]
        for zone, cap in a[m].groupby("gsp_group")["capacity_mw"].sum().items():
            rows.append({"pecd_tech": pecd_tech, "gsp_group": zone, "capacity_mw": cap})
    return pd.DataFrame(rows)


def national_series(gsp_wide: pd.DataFrame, year: int) -> pd.DataFrame:
    caps = _zone_capacities_for_year(year)
    out = {}
    for pecd_tech, spec in TECH_MAP.items():
        cols = [c for c in gsp_wide.columns if c.endswith(f"_{pecd_tech}")]
        if not cols:
            continue
        w = caps[caps["pecd_tech"] == pecd_tech].set_index("gsp_group")["capacity_mw"]
        zones = [c.rsplit(f"_{pecd_tech}", 1)[0] for c in cols]
        ww = w.reindex(zones).fillna(0.0)
        sub = gsp_wide[cols].copy()
        sub.columns = zones
        if ww.sum() > 0:
            out[spec["national_col"]] = (sub.mul(ww, axis=1).sum(axis=1) / ww.sum())
        else:
            out[spec["national_col"]] = sub.mean(axis=1)
    return pd.DataFrame(out)


def build_year(gsp_wide: pd.DataFrame, year: int) -> None:
    nat = national_series(gsp_wide, year)
    start = pd.Timestamp(f"{year}-01-01 00:00", tz="UTC")
    end = pd.Timestamp(f"{year + 1}-01-01 00:00", tz="UTC")
    idx = pd.date_range(start, end, freq=f"{RES}min", inclusive="left", tz="UTC")
    hourly = nat.reindex(pd.date_range(start, end, freq="1h", inclusive="left", tz="UTC"))
    half_hourly = hourly.reindex(idx, method="ffill", limit=1).round(4)
    half_hourly.index.name = "startTime"
    out = half_hourly.reset_index()
    dest = PROC_DIR / f"capacity_factors_pecd_{year}.csv"
    out.to_csv(dest, index=False)
    n_missing = half_hourly.isna().sum().sum()
    print(f"  {year}: {len(out):,} rows -> {dest.name} ({n_missing} half-hours still NaN "
          f"after ffill -- source gap, see cf_historical_gaps.csv)")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Collapse PECD NUTS-2 CF to national capacity_factors_pecd_{year}.csv.")
    p.add_argument("--years", nargs=2, type=int, metavar=("FROM", "TO"), default=None)
    args = p.parse_args(argv[1:])

    cf_path = PECD_DIR / "cf_historical.csv"
    if not cf_path.exists():
        sys.exit(f"{cf_path} missing; run gbpowerdata.build.pecd_build first.")
    cf_wide = pd.read_csv(cf_path, parse_dates=["startTime"]).set_index("startTime")
    if cf_wide.index.tz is None:
        cf_wide.index = cf_wide.index.tz_localize("UTC")
    gsp_wide = to_gsp_group_wide(cf_wide)

    years = (range(args.years[0], args.years[1] + 1) if args.years
            else range(cf_wide.index.year.min(), cf_wide.index.year.max() + 1))
    for year in years:
        build_year(gsp_wide, year)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
