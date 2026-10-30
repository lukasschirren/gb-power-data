"""The ERA5 weather record (PECD v4.2) as hourly capacity factors by GSP group, every year 1950-2025, and nationally.

WHY. A market model that clears observed years can ask how often a year like 2021 (still, dark) or 2023 (windy)
comes, and what its results look like over the whole weather record, only with a long series of the same weather
in the same shape it clears on. The Copernicus Pan-European Climate Database (PECD v4.2, ERA5-derived; `pull.pecd_pull`,
`build.pecd_build`) gives hourly capacity factors for onshore wind, offshore wind and solar per European zone from
1950. This stage keeps GB's, remapped to the 14 GSP groups the models' fleets are placed in, for every year, so a
model can weight the groups by any fleet it likes (today's, the Renewables Obligation's, a 2030 pathway's) and get
the national series that fleet would see.

METHOD. File by file (each raw file holds every European zone for a few years; only the UK columns are read), the
raw zones are put on PECD's own hourly stamps (`pecd_build.reindex_and_flag`), the wind zones re-weighted to NUTS-2
regions by the hand-curated zone maps (`common.pecd_regions`), and NUTS-2 to GSP groups by area weights
(`pecd_national_cf.to_gsp_group_wide`). Where files overlap the first value is kept. The national series on today's
fleet weights each group by the agents' capacity of `fleet_year` (`pecd_national_cf.national_series`), as the panel's
own PECD capacity factors do. The series are uncalibrated: PECD's stamps and levels as published (solar is
accumulated over the hour ending at its stamp, wind instantaneous at the stamp), to be calibrated by the model that
reads them against the metered record of its own years.

Ported on 30 Oct 2026 from the research repository's gbabm.build.pecd_return_periods (`national_from_raw`) and the
GSP-group part of its fig_cfd_vs_tax/reference.py. Fleet-weighted variants (the RO fleet's national series, the
return periods of a fleet's residual load) depend on a model's fleet and are built in the model from the GSP file.

OUTPUT processed/pecd/gsp_cf_era5.parquet: hourly, columns {gsp_group}_{onshore_wind|offshore_wind|solar_pv} (the
GSP groups as _A.._P), every raw year; processed/pecd/national_cf_historical.parquet: wind_offshore_cf,
wind_onshore_cf, solar_cf on the fleet of `fleet_year`. Reading the 76 years of raw files takes about ten minutes.
READ BY the merit-order model (weather years of its projection), `modelinputs`.
RUN    python -m gbpowerdata.build.weather_years [--fleet-year 2025]
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.build import pecd_build as pb
from gbpowerdata.build import pecd_national_cf as pnc
from gbpowerdata.common import pecd_regions

GSP_OUT = "gsp_cf_era5.parquet"
NATIONAL_OUT = "national_cf_historical.parquet"
RAW_TECHS = {"offshore_wind": "wind_offshore_cf", "onshore_wind": "wind_onshore_cf", "solar_pv": "solar_cf"}
# the fleet-weighting labels a model uses (tech of a weights table) -> raw technology and national column
TECH_RAW = {"Offshore": "offshore_wind", "Onshore": "onshore_wind", "Solar": "solar_pv"}


def file_gsp_wide(path: Path, raw_tech: str) -> pd.DataFrame:
    """One raw PECD file (a few years, every European zone) -> hourly CF per GSP group for `raw_tech`, reading only
    the UK columns; empty when the file has none."""
    head = pd.read_csv(path, comment="#", nrows=0).columns
    tcol = next((c for c in pb._TIME_CANDIDATES if c in head), head[0])
    uk = [c for c in head if c != tcol and str(c).startswith("UK")]
    if not uk:
        return pd.DataFrame()
    long = pb._to_long(pd.read_csv(path, comment="#", usecols=[tcol, *uk]))
    if raw_tech in pb._WIND_WEIGHTS:
        weight_fn, zone_col = pb._WIND_WEIGHTS[raw_tech]
        zone_tech = f"{raw_tech}_zone"
        wide_zone, _ = pb.reindex_and_flag(long, zone_tech)
        wide = (pecd_regions.reweight_wide(wide_zone, weight_fn(sorted(long["zone"].unique())), zone_col, zone_tech)
                .rename(columns=lambda c: c.replace(f"_{zone_tech}", f"_{raw_tech}")))
    else:
        wide, _ = pb.reindex_and_flag(long, raw_tech)
    return pnc.to_gsp_group_wide(wide)


def weighted_national(gsp_wide: pd.DataFrame, weights: pd.DataFrame, on_missing: str = "warn") -> pd.DataFrame:
    """National CF per technology from a GSP-group frame (columns {group}_{raw tech}), capacity-weighted with
    `weights` (tech in Offshore | Onshore | Solar, gsp_group, capacity_mw): groups without a column drop out and the
    rest are renormalised; weight dropped that way warns (on_missing "warn"), raises ("raise") or passes ("ignore")."""
    out = {}
    for tech, raw_tech in TECH_RAW.items():
        suf = f"_{raw_tech}"
        cols = [c for c in gsp_wide.columns if c.endswith(suf)]
        if not cols:
            continue
        zones = [c[: -len(suf)] for c in cols]
        wall = weights[weights["tech"] == tech].groupby("gsp_group")["capacity_mw"].sum()
        w = wall.reindex(zones).fillna(0.0)
        if not w.sum() > 0:
            raise ValueError(f"weather_years: no {tech} weight on any GSP group with an ERA5 series")
        lost = wall[~wall.index.isin(zones) & (wall > 0)]
        if len(lost) and on_missing != "ignore":
            msg = (f"weather_years: {lost.sum():.1f} MW of {tech} weight ({lost.sum() / wall.sum():.1%}) sits in GSP "
                   f"groups with no ERA5 series ({', '.join(map(str, lost.index))}); the rest is renormalised")
            if on_missing == "raise":
                raise ValueError(msg)
            warnings.warn(msg, stacklevel=2)
        sub = gsp_wide[cols].copy()
        sub.columns = zones
        out[RAW_TECHS[raw_tech]] = sub.mul(w, axis=1).sum(axis=1) / w.sum()
    return pd.DataFrame(out)


def build(raw_dir: Path | None = None, fleet_year: int = 2025, write: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The national series on `fleet_year`'s fleet and the GSP-group frame, over every raw file of each technology;
    written to processed/pecd/ when `write`."""
    raw_dir = pb.RAW_DIR if raw_dir is None else Path(raw_dir)
    nat_cols, gsp_parts = {}, []
    for raw_tech, col in RAW_TECHS.items():
        files = sorted(raw_dir.glob(f"{raw_tech}_*.csv"))
        if not files:
            raise FileNotFoundError(f"no raw PECD files for {raw_tech} in {raw_dir} "
                                    f"(python -m gbpowerdata.pull.pecd_pull --stream historical)")
        parts, keep = [], []
        for i, f in enumerate(files):
            g = file_gsp_wide(f, raw_tech)
            if g.empty:
                continue
            parts.append(pnc.national_series(g, fleet_year)[col])
            keep.append(g)
            if (i + 1) % 10 == 0:
                print(f"    {raw_tech}: {i + 1}/{len(files)} files", flush=True)
        s = pd.concat(parts)
        nat_cols[col] = s[~s.index.duplicated(keep="first")].sort_index()
        k = pd.concat(keep)
        gsp_parts.append(k[~k.index.duplicated(keep="first")].sort_index())
        print(f"  {raw_tech}: {len(files)} files, {nat_cols[col].index.min():%Y}-{nat_cols[col].index.max():%Y}, "
              f"mean CF {nat_cols[col].mean():.4f}", flush=True)
    nat = pd.DataFrame(nat_cols)
    nat.index.name = "startTime"
    gsp = pd.concat(gsp_parts, axis=1)
    gsp.index.name = "startTime"
    if write:
        out = cfg.processed_dir() / "pecd"
        out.mkdir(parents=True, exist_ok=True)
        nat.to_parquet(out / NATIONAL_OUT)
        gsp.to_parquet(out / GSP_OUT)
        print(f"wrote {out / NATIONAL_OUT} ({len(nat):,} hours) and {out / GSP_OUT} ({gsp.shape[1]} columns)")
    return nat, gsp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fleet-year", type=int, default=2025, help="the agents' year whose zone capacities weight the national series")
    a = ap.parse_args(argv)
    build(fleet_year=a.fleet_year)
    return 0


if __name__ == "__main__":
    sys.exit(main())
