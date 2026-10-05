"""Build wide hourly PECD v4.2 capacity-factor / temperature CSVs from the raw CDS cache.

Reads whatever `gbpowerdata.pull.pecd_pull` cached under `data/raw/pecd/historical/`, reindexes each
technology onto a real Gregorian UTC hourly spine (historical/ERA5 only in this pass -- no
non-standard calendar to decode, unlike a future CMIP6 projection stream would need; see the
module docstring of `pecd_pull` for why that's deferred), and pivots to WIDE format: one column
per `{nuts2}_{tech}` -- e.g. `UKC1_solar_pv` -- matching the ninja pipeline's units (capacity
factor 0-1, `renninja_pull.py`'s `#capacity=1, raw=false => electricity is the capacity factor`)
and UTC convention exactly.

Solar PV and temperature arrive already NUTS-2/SZON-coded from CDS. Onshore AND offshore wind do
NOT -- confirmed against the live CDS constraints endpoint (`gbpowerdata.pull.pecd_pull`'s docstring),
pecd4_2 has no NUTS-2 option for either wind variable, only PEON/PEOF energy zones -- so both are
remapped onto NUTS-2 via the hand-curated tables in `gbpowerdata.common.pecd_regions`
(`pecd_onshore_zone_to_nuts2.csv` / `pecd_offshore_zone_to_nuts2.csv`), which raise a clear,
actionable error listing exactly which zone codes are still unmapped if either is incomplete.

"No silent gap filling; flag missing hours": any hour missing from the reindexed spine is left NaN
and written to a companion `_gaps.csv` (startTime, column, reason) -- never interpolated here.

CONFIRMED against a live pull (2020-2021, all four techs, 2026-09-29): raw files are WIDE
(`Date, <zone1>, <zone2>, ...`, one row per hour) with a `#`-prefixed metadata preamble
(`load_raw_tech`'s `comment="#"`); `_to_long()`'s wide-shape branch handles this directly.

Usage:
  python -m gbpowerdata.build.pecd_build                 # all techs cached under data/raw/pecd/historical/
  python -m gbpowerdata.build.pecd_build --tech onshore_wind
Output:
  data/processed/pecd/cf_historical.csv                      (onshore_wind, offshore_wind, solar_pv)
  data/processed/pecd/temperature_popweighted_historical.csv (national value broadcast to every
                                                               NUTS-2 column -- TAW is SZON-only,
                                                               see gbpowerdata.pull.pecd_pull's VARIABLES)
  data/processed/pecd/cf_historical_gaps.csv
  data/processed/pecd/temperature_popweighted_historical_gaps.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import pecd_regions
from gbpowerdata.pull.pecd_pull import OUT_DIR as RAW_DIR
from gbpowerdata.pull.pecd_pull import PECD_RAW_DIR, VARIABLES

PROC_DIR = cfg.processed_dir() / "pecd"
CF_TECHS = ("onshore_wind", "offshore_wind", "solar_pv")
TEMP_TECHS = ("temperature_popweighted",)

_TIME_CANDIDATES = ("time", "Time", "TIME", "Date", "date", "timestamp", "startTime")


def _to_long(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise either a wide (time + one column per zone) or long (time, zone, value) raw CSV
    to a canonical long frame [time, zone, value]. Raises rather than guessing on an unrecognised
    shape."""
    time_col = next((c for c in _TIME_CANDIDATES if c in df.columns), df.columns[0])
    rest = [c for c in df.columns if c != time_col]
    if {"zone", "value"}.issubset(set(c.lower() for c in rest)):
        zone_col = next(c for c in rest if c.lower() == "zone")
        value_col = next(c for c in rest if c.lower() == "value")
        long = df[[time_col, zone_col, value_col]].rename(
            columns={time_col: "time", zone_col: "zone", value_col: "value"})
    elif len(rest) >= 1:
        long = df.melt(id_vars=[time_col], value_vars=rest, var_name="zone", value_name="value")
        long = long.rename(columns={time_col: "time"})
    else:
        raise ValueError(f"Can't identify zone columns in raw PECD file (columns={list(df.columns)}); "
                         "check the real CDS CSV layout and update pecd_build._to_long().")
    long["time"] = pd.to_datetime(long["time"], utc=True)
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    return long


def load_raw_tech(tech: str, raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Each raw file opens with a `#`-prefixed metadata preamble (title, citation, licence,
    spatial/temporal extent -- ~50 lines, confirmed against a real pull), same convention as
    renewables.ninja's own CSVs (`renninja_pull.py`'s `pd.read_csv(..., comment="#")`)."""
    files = sorted(raw_dir.glob(f"{tech}_*.csv"))
    if not files:
        sys.exit(f"No raw PECD files for {tech!r} in {raw_dir}; run gbpowerdata.pull.pecd_pull first.")
    frames = [_to_long(pd.read_csv(f, comment="#")) for f in files]
    long = pd.concat(frames, ignore_index=True).drop_duplicates(["time", "zone"])
    return long.sort_values(["zone", "time"])


def _spine(long: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.date_range(long["time"].min().floor("h"), long["time"].max().ceil("h"),
                         freq="1h", tz="UTC")


def reindex_and_flag(long: pd.DataFrame, tech: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Long -> wide {zone}_{tech} on a real UTC hourly spine; returns (wide, gaps)."""
    idx = _spine(long)
    wide = long.pivot_table(index="time", columns="zone", values="value").reindex(idx)
    wide.columns = [f"{z}_{tech}" for z in wide.columns]
    wide.index.name = "startTime"

    gaps = (wide.isna().stack()[lambda s: s]
           .reset_index().rename(columns={"startTime": "startTime", "level_1": "column"})
           .iloc[:, [0, 1]])
    gaps.columns = ["startTime", "column"]
    gaps["reason"] = "missing_from_source"
    return wide.round(4), gaps


# tech -> (zone-weight loader, weight-table zone column). Neither wind variable has a NUTS-2
# option in pecd4_2 (confirmed against the live CDS constraints endpoint -- only PEON/PEOF energy
# zones exist), so both go through the same hand-curated zone->NUTS-2 remap; solar_pv arrives
# already NUTS-2-coded and needs none.
_WIND_WEIGHTS = {
    "onshore_wind": (pecd_regions.onshore_zone_weights, "pecd_onshore_zone"),
    "offshore_wind": (pecd_regions.offshore_zone_weights, "pecd_offshore_zone"),
}


def build_cf(techs: tuple[str, ...] = CF_TECHS, raw_dir: Path = RAW_DIR, stem: str = "historical") -> None:
    wides, gaps = [], []
    for tech in techs:
        if not sorted(raw_dir.glob(f"{tech}_*.csv")):
            print(f"  skip {tech} (no raw files)")
            continue
        long = load_raw_tech(tech, raw_dir)
        long = long[long["zone"].astype(str).str.startswith("UK")]
        if tech in _WIND_WEIGHTS:
            weight_fn, zone_col = _WIND_WEIGHTS[tech]
            zones = sorted(long["zone"].unique())
            weights = weight_fn(zones)
            zone_tech = f"{tech}_zone"
            wide_zone, gap = reindex_and_flag(long, zone_tech)
            wides.append(pecd_regions.reweight_wide(wide_zone, weights, zone_col, zone_tech)
                        .rename(columns=lambda c: c.replace(f"_{zone_tech}", f"_{tech}")))
            gaps.append(gap)
        else:
            wide, gap = reindex_and_flag(long, tech)
            wides.append(wide)
            gaps.append(gap)
    if not wides:
        print(f"No CF technologies had raw data for {stem}; nothing built.")
        return
    out = pd.concat(wides, axis=1).reset_index()
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(PROC_DIR / f"cf_{stem}.csv", index=False)
    pd.concat(gaps, ignore_index=True).to_csv(PROC_DIR / f"cf_{stem}_gaps.csv", index=False)
    print(f"Saved {out.shape[0]:,} rows x {out.shape[1]-1} columns -> cf_{stem}.csv "
          f"({sum(len(g) for g in gaps):,} flagged gaps)")


def build_cf_future(gcm: str, scenario: str, techs: tuple[str, ...] = ("onshore_wind", "offshore_wind")) -> None:
    """Same build as `build_cf()`, pointed at one GCM/scenario's projection raw cache
    (`data/raw/pecd/projection/{gcm}/{scenario}/`) -> `data/processed/pecd/cf_future_{gcm}_{scenario}.csv`."""
    raw_dir = PECD_RAW_DIR / "projection" / gcm / scenario
    if not raw_dir.exists():
        print(f"  skip {gcm}/{scenario} (no raw dir -- not pulled yet)")
        return
    build_cf(techs, raw_dir, f"future_{gcm}_{scenario}")


def build_temperature() -> None:
    tech = "temperature_popweighted"
    if not sorted(RAW_DIR.glob(f"{tech}_*.csv")):
        print(f"  skip {tech} (no raw files)")
        return
    long = load_raw_tech(tech)
    # SZON is national-for-GB; broadcast the single national series across every GB NUTS-2 column
    # the CF build produced, rather than fabricating a per-region disaggregation PECD doesn't offer.
    cf_path = PROC_DIR / "cf_historical.csv"
    if not cf_path.exists():
        sys.exit("Build cf_historical.csv first (build_cf()) -- temperature broadcasts onto its "
                 "NUTS-2 column set.")
    # Any NUTS-2-coded CF tech gives the same code set (all cover the whole of GB); prefer
    # solar_pv since it's NUTS-2-native (never zone-remapped), falling back to onshore_wind if
    # solar wasn't built this run.
    cf_cols = pd.read_csv(cf_path, nrows=0).columns
    nuts2_codes = []
    for t in ("solar_pv", "onshore_wind"):
        nuts2_codes = sorted({c.rsplit(f"_{t}", 1)[0] for c in cf_cols if c.endswith(f"_{t}")})
        if nuts2_codes:
            break
    if not nuts2_codes:
        sys.exit(f"{cf_path.name} has no solar_pv or onshore_wind columns to broadcast "
                 "temperature onto -- build_cf() needs at least one of them included.")
    # SZON splits the UK into "UK00" (Great Britain) and "UKNI" (Northern Ireland -- its own
    # bidding zone, part of the Ireland SEM) -- confirmed against a real pull. UKNI is out of
    # scope the same way it is everywhere else in this GB-only repo (gsp_group's 14 zones,
    # ninja_sites.csv, etc.); UK00 is the national value broadcast below.
    long = long[long["zone"] == "UK00"]
    wide, gap = reindex_and_flag(long, tech)
    if wide.shape[1] != 1:
        sys.exit(f"Expected exactly one 'UK00' column for GB temperature, got {list(wide.columns)}.")
    national = wide.iloc[:, 0]
    out = pd.DataFrame({f"{n}_{tech}": national.values for n in nuts2_codes}, index=national.index)
    out.index.name = "startTime"
    out = out.reset_index()
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(PROC_DIR / f"{tech}_historical.csv", index=False)
    gap.to_csv(PROC_DIR / f"{tech}_historical_gaps.csv", index=False)
    print(f"Saved {out.shape[0]:,} rows -> {tech}_historical.csv (national value broadcast to "
          f"{len(nuts2_codes)} NUTS-2 columns; {len(gap):,} flagged gaps)")


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Build wide PECD CF/temperature CSVs (historical or future).")
    p.add_argument("--tech", nargs="*", choices=list(VARIABLES), default=list(VARIABLES))
    p.add_argument("--stream", choices=["historical", "future"], default="historical")
    p.add_argument("--gcm", nargs="*", default=None, help="future only; default: every GCM pulled.")
    p.add_argument("--scenario", nargs="*", default=None, help="future only; default: every scenario pulled.")
    args = p.parse_args(argv[1:])

    cf_techs = tuple(t for t in CF_TECHS if t in args.tech)
    if args.stream == "historical":
        if cf_techs:
            build_cf(cf_techs)
        if set(args.tech) & set(TEMP_TECHS):
            build_temperature()
        return

    proj_dir = PECD_RAW_DIR / "projection"
    gcms = args.gcm or sorted(p.name for p in proj_dir.glob("*") if p.is_dir())
    for gcm in gcms:
        scenarios = args.scenario or sorted(p.name for p in (proj_dir / gcm).glob("*") if p.is_dir())
        for scenario in scenarios:
            build_cf_future(gcm, scenario, cf_techs or ("onshore_wind", "offshore_wind"))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
