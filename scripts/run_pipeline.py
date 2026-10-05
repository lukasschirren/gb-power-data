"""Run the full data pipeline across the 2018-2025 panel.

Per year the year is injected via the PIPELINE_YEAR env var (config.load_config
reads it), so each stage runs as a clean subprocess without editing config.yaml.

  build_cfd_status      (once; year-independent per-CfD-unit status table)
  for each year:
    stage1_tag_plants     -> powerplants_tagged_{year}.csv
    stage1_spatial_join   -> powerplants_located_{year}.csv   (gsp_id + gsp_group)
    stage2_build_timeseries -> demand/capacity_factors/fuel_prices/mid_target_{year}.csv
    build_cfd_fleet       -> cfd_fleet_{year}.csv (LCCC actual-paying fleet; after stage 2,
                             because a part-year contract's delivery weight is CF-weighted
                             with capacity_factors_{year}.csv, else a flat share of the year)
    stage2c_zone_demand   -> demand_by_zone_{year}.csv         (14 GSP groups)
    stage3_build_agents   -> agents_{year}.csv                 (located, zone-tagged)
    stage2b_zone_cf       -> capacity_factors_by_zone_{year}.csv  (needs the per-zone
                             renewables.ninja pull; soft — skipped if not yet pulled)
    stage2d_wind_farms    -> wind_farms_{year}.csv + wind_farm_fpn_{year}.csv (transmission
                             wind farms on observed FPN, for the comb's --vre-profile farm;
                             soft — needs the FPN pull and data/reference/wind_farm_map.csv)

Locational setup (run once, not per-year — see the GSP phase scope):
  python -m gbpowerdata.pull.build_zone_sites          # -> data/reference/ninja_sites_by_zone.csv
  python -m gbpowerdata.pull.renninja_pull --sites-file ninja_sites_by_zone.csv  # long, rate-limited
  python -m gbpowerdata.pull.fpn_pull                  # -> data/raw/fpn/ (per-unit notifications)
  python scripts/build_wind_farm_map.py          # -> data/reference/wind_farm_map.csv

Usage:
  python scripts/run_pipeline.py                 # 2018-2025
  python scripts/run_pipeline.py 2023            # one year
  python scripts/run_pipeline.py 2020 2021 2022  # a subset
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DEFAULT_YEARS = range(2018, 2026)

# Lines worth surfacing from each stage's (otherwise verbose) output.
KEEP = ("Total renewable", "Saved", "CF validation", "wind_offshore", "wind_onshore",
        "solar_cf", "national    ", "gas p/therm", "carbon GBP", "MID target sources",
        "Total capacity", "CfD net settlement", "Authoritative CfD fleet",
        "Location method", "located capacity", "Additivity", "GSP group", "reconcile",
        "WARNING")


def run(module: str, year: int | None = None, soft: bool = False) -> None:
    env = dict(os.environ)
    # Make the gbpowerdata package importable even without `pip install -e .`.
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH", "")) if p)
    if year is not None:
        env["PIPELINE_YEAR"] = str(year)
    r = subprocess.run([sys.executable, "-m", f"gbpowerdata.build.{module}"], env=env, cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        tag = "skipped (soft)" if soft else "FAILED"
        print(f"  !! {module} {tag} (year={year})")
        print((r.stdout or "")[-800:])
        print((r.stderr or "")[-800:])
        if not soft:
            sys.exit(1)
        return
    for ln in r.stdout.splitlines():
        if any(k in ln for k in KEEP):
            print(f"    {ln.strip()}")


def main(argv: list[str]) -> None:
    years = [int(a) for a in argv[1:]] or list(DEFAULT_YEARS)
    print("=== build_cfd_status (panel) ===")
    run("build_cfd_status")
    # Empirical per-year nuclear availability (needs powerplants_located_* from a prior
    # pass; soft — a cold run skips it and Stage 3 falls back to the flat 0.65).
    run("nuclear_availability", soft=True)
    for y in years:
        print(f"\n=== {y} ===")
        run("stage1_tag_plants", y)
        run("stage1_spatial_join", y)
        run("stage2_build_timeseries", y)
        run("build_cfd_fleet", y)      # reads capacity_factors_{y}.csv from stage 2
        run("stage2c_zone_demand", y)
        run("stage3_build_agents", y)
        run("stage2b_zone_cf", y, soft=True)  # needs the per-zone ninja pull
        run("stage2d_wind_farms", y, soft=True)  # needs the FPN pull and the wind-farm map
    print(f"\nDone: {len(years)} year(s) -> data/processed/")


if __name__ == "__main__":
    main(sys.argv)
