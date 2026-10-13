"""Pull per-unit half-hourly Physical Notifications (Elexon PN / FPN) for the GB
generation fleet -> data/raw/fpn/{bmUnit}.csv (one file per BM unit; resumable).

PN = "Physical Notifications": each BM unit's declared MW profile per settlement period,
as (timeFrom, timeTo, levelFrom, levelTo) segments. The last PN submitted before gate
closure is the Final Physical Notification (FPN). Free, no key, via /datasets/PN/stream
(the same host + pattern as b1610_pull.py).

Why this on top of B1610:
  * B1610 is METERED output but thermal-only (~100 units) and starts 2019.
  * PN/FPN is a DECLARATION but covers the WHOLE dispatchable fleet — wind, pumped storage,
    nuclear, gas, biomass, hydro — back to 2016. That whole-fleet, longer coverage is what
    lets us validate per-unit VOLUME attribution against who-declared-what.
Caveat: a PN is a declaration, not settlement metering; it can differ from B1610 around
dynamic/curtailment events. For steady generation the two agree closely — the build step
cross-checks them where both exist.

Universe: transmission (T_) BM units whose fuelType is a generation fuel, from the current
BM-unit snapshot (same source + delisting caveat as b1610_pull.py). Interconnectors (I_) are
opt-in via --interconnectors. --storage-fleet pulls instead every unit of
data/processed/storage_fleet.csv with an Elexon id: the T_ and E_ storage units, and the supplier
(2__) and virtual lead party (V__) units NESO's results name as batteries, which the register
gives no fuel type but which notify like any BM unit (all six sampled on 20 Nov 2025 did).

Usage:
  python -m gbpowerdata.pull.fpn_pull                              # all T_ generation units, 2016-2026
  python -m gbpowerdata.pull.fpn_pull --start 2023-01-01 --end 2024-01-01
  python -m gbpowerdata.pull.fpn_pull --fuel NUCLEAR CCGT          # only these fuel types
  python -m gbpowerdata.pull.fpn_pull --limit 5                    # first 5 units (smoke test)
  python -m gbpowerdata.pull.fpn_pull --interconnectors           # add I_ interconnector units
  python -m gbpowerdata.pull.fpn_pull --storage-fleet             # storage_fleet's units (after its build)
"""

from __future__ import annotations

import argparse
import re
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

STREAM = "https://data.elexon.co.uk/bmrs/api/v1/datasets/PN/stream"
# generation fuel types in the BM-unit snapshot (excludes pure demand / storage-charge rows)
GEN_FUELS = {"WIND", "CCGT", "OCGT", "NUCLEAR", "BIOMASS", "COAL", "OIL", "NPSHYD", "PS", "OTHER"}
KEEP = ["settlementDate", "settlementPeriod", "timeFrom", "timeTo", "levelFrom", "levelTo"]
OUT = cfg.raw_dir() / "fpn"
SLEEP = 0.25


def gen_units(fuels: set[str] | None = None, interconnectors: bool = False) -> pd.DataFrame:
    """Generation BM units (elexonBmUnit + fuelType + capacity) from the latest snapshot."""
    bm = pd.read_csv(sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1])
    u = bm["elexonBmUnit"].astype(str)
    want = fuels or GEN_FUELS
    m = bm["fuelType"].isin(want) & u.str.startswith("T_")
    if interconnectors:
        m = m | (u.str.startswith("I_") & bm["fuelType"].astype(str).str.startswith("INT"))
    cols = ["elexonBmUnit", "fuelType", "generationCapacity"]
    d = bm.loc[m, cols].dropna(subset=["elexonBmUnit"]).copy()
    return d.sort_values(["fuelType", "elexonBmUnit"]).reset_index(drop=True)


def battery_units() -> pd.DataFrame:
    """Every battery/BESS BM unit (any prefix incl embedded E_) — fuelType OTHER identified by the
    BMU type-letter B before the unit number or a battery keyword in the name/party."""
    bm = pd.read_csv(sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1]).drop_duplicates("elexonBmUnit")
    oth = bm[bm["fuelType"] == "OTHER"].dropna(subset=["elexonBmUnit"]).copy()

    def is_batt(row) -> bool:
        code = re.sub(r"^[A-Z0-9]+_+", "", str(row["elexonBmUnit"]))
        m = re.search(r"([A-Za-z])-?\d+$", code)
        letter = m.group(1).upper() if m else ""
        name = f"{row.get('bmUnitName')} {row.get('leadPartyName')}".upper()
        return letter == "B" or any(k in name for k in ("BATT", "BESS", "STORAGE"))

    b = oth[oth.apply(is_batt, axis=1)][["elexonBmUnit", "fuelType", "generationCapacity"]]
    return b.sort_values("elexonBmUnit").reset_index(drop=True)


def storage_fleet_units() -> pd.DataFrame:
    """Every unit of storage_fleet with an Elexon id (gbpowerdata.build.storage_fleet; its technology as fuelType)."""
    from gbpowerdata import processed as P

    f = P.read_storage_fleet()
    f = f[f["kind"].isin(["bm", "supplier", "vlp"])]
    d = pd.DataFrame({"elexonBmUnit": f["unit_id"].astype(str), "fuelType": f["tech"],
                      "generationCapacity": f["capacity_mw"]})
    return d.sort_values("elexonBmUnit").reset_index(drop=True)


def pull_unit(u: str, years: range) -> None:
    out = OUT / f"{u.replace('/', '_')}.csv"
    if out.exists():
        print(f"  skip {u} (exists)", flush=True)
        return
    frames = []
    for y in years:
        try:
            r = requests.get(STREAM, params={"from": f"{y}-01-01", "to": f"{y + 1}-01-01",
                                             "bmUnit": u}, timeout=180)
            r.raise_for_status()
        except requests.RequestException as e:                       # transient API hiccup
            print(f"  {u} {y}: request failed ({e}); retrying once", flush=True)
            time.sleep(2.0)
            r = requests.get(STREAM, params={"from": f"{y}-01-01", "to": f"{y + 1}-01-01",
                                             "bmUnit": u}, timeout=180)
            r.raise_for_status()
        data = r.json()
        if data:
            frames.append(pd.DataFrame(data)[KEEP])
        time.sleep(SLEEP)
    if not frames:
        print(f"  {u}: no data", flush=True)
        return
    df = pd.concat(frames, ignore_index=True)
    df = (df.drop_duplicates(["settlementDate", "settlementPeriod", "timeFrom"])
          .sort_values(["settlementDate", "settlementPeriod", "timeFrom"]))
    df.to_csv(out, index=False)
    print(f"  {u}: {len(df):,} rows -> {out.name}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull per-unit PN/FPN for GB generation BM units.")
    p.add_argument("--start", default="2016-01-01")
    p.add_argument("--end", default="2026-01-01")
    p.add_argument("--fuel", nargs="*", help="restrict to these fuelTypes (default: all generation)")
    p.add_argument("--interconnectors", action="store_true", help="also pull I_ interconnector units")
    p.add_argument("--batteries", action="store_true",
                   help="pull the battery/BESS fleet (any prefix incl embedded E_) instead")
    p.add_argument("--storage-fleet", action="store_true",
                   help="pull every unit of storage_fleet with an Elexon id (supplier and VLP batteries included) instead")
    p.add_argument("--limit", type=int, help="only the first N units (smoke test)")
    args = p.parse_args(argv[1:])
    years = range(int(args.start[:4]), int(args.end[:4]))

    OUT.mkdir(parents=True, exist_ok=True)
    fuels = {f.upper() for f in args.fuel} if args.fuel else None
    if args.storage_fleet:
        units = storage_fleet_units()
    else:
        units = battery_units() if args.batteries else gen_units(fuels, interconnectors=args.interconnectors)
    if args.limit:
        units = units.head(args.limit)
    print(f"{len(units)} units x {len(list(years))} years -> {OUT}", flush=True)
    print(units["fuelType"].value_counts().to_string(), flush=True)
    for row in units.itertuples():
        pull_unit(row.elexonBmUnit, years)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
