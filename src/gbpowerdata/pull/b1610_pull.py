"""Pull per-unit half-hourly generation (Elexon B1610) for the dispatchable thermal
fleet -> data/raw/b1610/{bmUnit}.csv (one file per BM unit; resumable).

B1610 = "Actual Generation Output Per Generation Unit". Free, no key, via the
/datasets/B1610/stream endpoint (date range + bmUnit). Pulls the transmission-
connected thermal units (NUCLEAR, COAL, CCGT, OCGT, BIOMASS, OIL) for per-unit
availability / ramp / min-stable characterisation (see reports/text/technology_flexibility.md).

Caveat: the unit list comes from the CURRENT BM-unit snapshot, so plants that
retired AND were delisted before that snapshot (the 2018-2019 coal of Aberthaw B,
Cottam and Eggborough, and Deeside's CCGT) are not covered; Elexon's per-unit query
returns nothing for them anyway, and their notifications come from its all-units
stream instead (gbpowerdata.pull.fpn_left_register_pull).

The default list holds the T_ units only. Elexon publishes B1610 for the embedded (E_) units
too: the CCGTs connected to a distribution network (Shoreham E_SHOS-1, Great Yarmouth E_GYAR-1,
King's Lynn E_KLYN-A-1, Peterborough E_PETEM1, Corby E_CORB-1, Fawley E_FAWN-1, Fellside
E_FELL-1, Glanford Brigg E_BRGG-1) are pulled by naming them with --units, as for the run and
down times of gbpowerdata.build.unit_runs.

Usage:
  python -m gbpowerdata.pull.b1610_pull                          # all thermal T_ units, 2018-2026
  python -m gbpowerdata.pull.b1610_pull --start 2022-01-01 --end 2023-01-01
  python -m gbpowerdata.pull.b1610_pull --units E_SHOS-1 E_GYAR-1 --start 2019-01-01
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

STREAM = "https://data.elexon.co.uk/bmrs/api/v1/datasets/B1610/stream"
THERMAL = {"NUCLEAR", "COAL", "CCGT", "OCGT", "BIOMASS", "OIL"}
OUT = cfg.raw_dir() / "b1610"
SLEEP = 0.25


def thermal_units() -> list[str]:
    bm = pd.read_csv(sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1])
    d = bm[bm["fuelType"].isin(THERMAL)
           & bm["elexonBmUnit"].astype(str).str.startswith("T_")]
    return sorted(d["elexonBmUnit"].dropna().astype(str).unique())


def pull_unit(u: str, years: range) -> None:
    out = OUT / f"{u.replace('/', '_')}.csv"
    if out.exists():
        print(f"  skip {u} (exists)", flush=True)
        return
    frames = []
    for y in years:
        r = requests.get(STREAM, params={"from": f"{y}-01-01", "to": f"{y + 1}-01-01",
                                         "bmUnit": u}, timeout=180)
        r.raise_for_status()
        data = r.json()
        if data:
            frames.append(pd.DataFrame(data))
        time.sleep(SLEEP)
    if not frames:
        print(f"  {u}: no data", flush=True)
        return
    df = pd.concat(frames, ignore_index=True)[
        ["bmUnit", "settlementDate", "settlementPeriod", "halfHourEndTime", "quantity"]]
    df = (df.drop_duplicates(["settlementDate", "settlementPeriod"])
          .sort_values(["settlementDate", "settlementPeriod"]))
    df.to_csv(out, index=False)
    print(f"  {u}: {len(df):,} rows -> {out.name}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull per-unit B1610 for thermal BM units.")
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default="2026-01-01")
    p.add_argument("--units", nargs="+", metavar="BMUNIT",
                   help="Elexon BM unit ids to pull instead of the register's thermal T_ units")
    args = p.parse_args(argv[1:])
    years = range(int(args.start[:4]), int(args.end[:4]))

    OUT.mkdir(parents=True, exist_ok=True)
    units = args.units or thermal_units()
    what = "named" if args.units else "thermal T_"
    print(f"{len(units)} {what} units x {len(list(years))} years -> {OUT}", flush=True)
    for u in units:
        pull_unit(u, years)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
