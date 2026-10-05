"""Pull per-unit Balancing-Mechanism bid-offer data (Elexon BOD + BOALF).

This is the one dataset that prices generator offers DIRECTLY and by technology: BOD =
"Bid-Offer Data", each BM unit's SUBMITTED bid/offer price ladder per settlement period
(pairId, levelFrom/levelTo MW, `offer` and `bid` £/MWh). Unlike the anonymous day-ahead
exchange curves, every row is tagged to a BMU whose technology is known exactly via
`bm_units_*.csv` `fuelType`. BOALF = "Bid-Offer Acceptance Level Flagged", the acceptances
(which offers/bids the system operator actually took, and when) — sparse.

Caveat for interpretation: BOD is the BALANCING-mechanism offer, not the wholesale
day-ahead bid — a different product (real-time, physical, strategic) and only the balancing
volume, not the whole market. It is a tech-tagged *benchmark* for "which technology bids
where", not the wholesale bid itself.

Free, no key, via /datasets/{BOD,BOALF}/stream (date range + bmUnit). One CSV per BM unit,
resumable (skip if exists). Universe = transmission generation units (T_) across the fleet;
technology comes from the newest bm_units snapshot.

Usage:
  python -m gbpowerdata.pull.elexon_bod_pull                          # BOD+BOALF, T_ gen, 2022-2025
  python -m gbpowerdata.pull.elexon_bod_pull --datasets BOD --start 2023-01-01 --end 2024-01-01
"""

from __future__ import annotations

import argparse
import re
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

STREAM = "https://data.elexon.co.uk/bmrs/api/v1/datasets/{ds}/stream"
# Generation fuels (mirrors fpn_pull) — include WIND so the "VRE bids <= floor" view works.
GEN_FUELS = {"WIND", "CCGT", "OCGT", "NUCLEAR", "BIOMASS", "COAL", "OIL", "NPSHYD", "PS", "OTHER"}
# BOD has a fixed schema; BOALF's varies, so keep it whole.
BOD_COLS = ["bmUnit", "settlementDate", "settlementPeriod", "timeFrom", "timeTo",
            "levelFrom", "levelTo", "pairId", "offer", "bid"]
SLEEP = 0.25


def gen_units() -> list[str]:
    bm = pd.read_csv(sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1])
    d = bm[bm["fuelType"].isin(GEN_FUELS)
           & bm["elexonBmUnit"].astype(str).str.startswith("T_")]
    return sorted(d["elexonBmUnit"].dropna().astype(str).unique())


def battery_units() -> list[str]:
    """Every battery/BESS BM unit, ANY prefix (T_/E_/V__/2__). Batteries carry fuelType OTHER;
    identify by the BMU type-letter B before the unit number (e.g. E_ARBRB-1) or a battery keyword
    in the name/party. This is how the embedded (E_) fleet the T_-only pull missed gets included."""
    bm = pd.read_csv(sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1]).drop_duplicates("elexonBmUnit")
    oth = bm[bm["fuelType"] == "OTHER"].dropna(subset=["elexonBmUnit"]).copy()

    def is_batt(row) -> bool:
        code = re.sub(r"^[A-Z0-9]+_+", "", str(row["elexonBmUnit"]))
        m = re.search(r"([A-Za-z])-?\d+$", code)
        letter = m.group(1).upper() if m else ""
        name = f"{row.get('bmUnitName')} {row.get('leadPartyName')}".upper()
        return letter == "B" or any(k in name for k in ("BATT", "BESS", "STORAGE"))

    b = oth[oth.apply(is_batt, axis=1)]
    return sorted(b["elexonBmUnit"].astype(str).unique())


def _get_json(url: str, params: dict, tries: int = 5) -> list:
    """GET with retry+backoff — the Elexon stream endpoint intermittently drops connections."""
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=180)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            if i == tries - 1:
                raise
            time.sleep(2 ** i)      # 1,2,4,8s
    return []


def pull_unit(u: str, years: range, dataset: str) -> None:
    out = cfg.raw_dir() / dataset.lower() / f"{u.replace('/', '_')}.csv"
    if out.exists():
        return
    frames = []
    for y in years:
        data = _get_json(STREAM.format(ds=dataset),
                         {"from": f"{y}-01-01", "to": f"{y + 1}-01-01", "bmUnit": u})
        if data:
            frames.append(pd.DataFrame(data))
        time.sleep(SLEEP)
    if not frames:
        return
    df = pd.concat(frames, ignore_index=True)
    if dataset == "BOD":
        df = (df[[c for c in BOD_COLS if c in df.columns]]
              .drop_duplicates(["settlementDate", "settlementPeriod", "pairId"])
              .sort_values(["settlementDate", "settlementPeriod", "pairId"]))
    else:  # BOALF — variable schema; keep all, dedup on the natural key when present
        keys = [c for c in ["settlementDate", "settlementPeriod", "acceptanceNumber", "pairId"]
                if c in df.columns]
        df = df.drop_duplicates(keys or None).sort_values(
            [c for c in ["settlementDate", "settlementPeriod"] if c in df.columns])
    df.to_csv(out, index=False)
    print(f"  {dataset} {u}: {len(df):,} rows -> {out.name}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull per-unit BM bid-offer data (BOD + BOALF).")
    p.add_argument("--datasets", nargs="+", default=["BOD", "BOALF"], choices=["BOD", "BOALF"])
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2026-01-01")
    p.add_argument("--batteries", action="store_true",
                   help="pull the battery/BESS fleet (any prefix incl embedded E_), not T_ gen")
    args = p.parse_args(argv[1:])
    years = range(int(args.start[:4]), int(args.end[:4]))

    units = battery_units() if args.batteries else gen_units()
    for ds in args.datasets:
        (cfg.raw_dir() / ds.lower()).mkdir(parents=True, exist_ok=True)
        print(f"{ds}: {len(units)} T_ gen units x {len(list(years))} years", flush=True)
        for u in units:
            try:
                pull_unit(u, years, ds)
            except Exception as e:                 # persistent failure: log, keep going (resumable)
                print(f"  FAIL {ds} {u}: {e}", flush=True)
    print("Done.")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
