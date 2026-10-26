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

`--fuel WIND` pulls every wind unit of the newest register snapshot with a T_ or E_ id (215 on 5 Jun 2026: the
transmission-connected farms and the embedded ones with BM units, which FUELHH's WIND meters together), for
gbpowerdata.build.generation_mix's split of metered wind into offshore and onshore. The supplier (2__) and the two
C__ units are left out, and so are farms the register lists without an Elexon id (B1610 is queried by that id).

`--storage-fleet` pulls every unit of data/processed/storage_fleet.csv with an Elexon id (as fpn_pull
--storage-fleet does): the T_ and E_ batteries and pumped storage units, and the supplier (2__) and virtual lead
party (V__) units NESO's results name as batteries, for gbpowerdata.build.generation_battery. Elexon publishes their
metered output as for any BM unit, signed (negative while charging): pulled on 26 Oct 2026 for 2018-2026, it returned
data for 238 of the 239 units (all 118 T_/E_ batteries, 17 pumped storage units, 69 supplier and 34 of 35 virtual lead
party units; none for V__BCEND002, in the fleet from 7 Apr to 30 May 2022), from 1 Feb 2019 to 19 Oct 2026.

Usage:
  python -m gbpowerdata.pull.b1610_pull                          # all thermal T_ units, 2018-2026
  python -m gbpowerdata.pull.b1610_pull --start 2022-01-01 --end 2023-01-01
  python -m gbpowerdata.pull.b1610_pull --units E_SHOS-1 E_GYAR-1 --start 2019-01-01
  python -m gbpowerdata.pull.b1610_pull --fuel WIND --end 2027-01-01   # every wind unit, 2018 to date
  python -m gbpowerdata.pull.b1610_pull --storage-fleet --end 2027-01-01   # storage_fleet's units (after its build)
A unit's file, once written, is kept: delete it to pull the unit again (the year to date is then extended).
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


def fuel_units(fuel: str) -> list[str]:
    """The newest register snapshot's units of `fuel` (its fuelType) with a T_ or E_ Elexon id."""
    bm = pd.read_csv(sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1])
    ids = bm.loc[bm["fuelType"].eq(fuel), "elexonBmUnit"].dropna().astype(str)
    return sorted(ids[ids.str.match(r"[TE]_")].unique())


def get_year(u: str, y: int, tries: int = 5) -> list:
    """One unit-year from the stream, retried with a growing pause: a long pull meets dropped connections and
    failed name lookups (the storage fleet's stopped at its 24th unit on one, 26 Oct 2026)."""
    for k in range(tries):
        try:
            r = requests.get(STREAM, params={"from": f"{y}-01-01", "to": f"{y + 1}-01-01", "bmUnit": u}, timeout=180)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout):
            if k == tries - 1:
                raise
            time.sleep(30 * (k + 1))


def pull_unit(u: str, years: range) -> None:
    out = OUT / f"{u.replace('/', '_')}.csv"
    if out.exists():
        print(f"  skip {u} (exists)", flush=True)
        return
    frames = []
    for y in years:
        data = get_year(u, y)
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
    p.add_argument("--fuel", metavar="FUELTYPE",
                   help="every T_ and E_ unit of this register fuel type (e.g. WIND) instead of the thermal T_ units")
    p.add_argument("--storage-fleet", action="store_true",
                   help="every unit of storage_fleet with an Elexon id (supplier and VLP batteries included) instead")
    args = p.parse_args(argv[1:])
    years = range(int(args.start[:4]), int(args.end[:4]))

    OUT.mkdir(parents=True, exist_ok=True)
    if args.storage_fleet:
        from gbpowerdata.pull.fpn_pull import storage_fleet_units
        units = storage_fleet_units()["elexonBmUnit"].tolist()
        what = "storage_fleet"
    else:
        units = args.units or (fuel_units(args.fuel) if args.fuel else thermal_units())
        what = "named" if args.units else (f"{args.fuel} T_ and E_" if args.fuel else "thermal T_")
    print(f"{len(units)} {what} units x {len(list(years))} years -> {OUT}", flush=True)
    for u in units:
        pull_unit(u, years)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
