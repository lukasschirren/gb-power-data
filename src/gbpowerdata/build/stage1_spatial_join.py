"""Stage 1b — locate every tagged plant in a GSP region (additive, locational).

Reads the Stage 1 output (powerplants_tagged_{year}.csv, which already carries
lat/lon) and assigns each plant its fine ``gsp_id`` (~330 GSP regions) and coarse
``gsp_group`` (14 zones, _A.._P) via a point-in-polygon join against the NESO GSP
boundaries (see gbpowerdata/common/gsp.py). Offshore/coastal plants snap to the nearest onshore
GSP and are correctable via data/reference/gsp_overrides.csv.

The copperplate baseline is untouched — this only adds zone columns. gsp_id rolls
up losslessly to gsp_group, which is where the demand/CF series live for now.

Validation: CfD-tagged plants are cross-checked against the LCCC CfD register's
own ``gsp_group`` (an independent label) and any mismatches are reported.

Output: data/processed/powerplants_located_{year}.csv
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import gsp

CFG = cfg.load_config()
YEAR = int(CFG["year"])


def cfd_register_groups() -> pd.Series:
    """contract_id -> gsp_group from the CfD register (independent cross-check)."""
    reg = pd.read_excel(cfg.raw_dir() / CFG["stage1"]["cfd_register"])
    return reg.dropna(subset=["gsp_group"]).set_index("contract_id")["gsp_group"]


def main() -> None:
    src = cfg.processed_dir() / f"powerplants_tagged_{YEAR}.csv"
    pp = pd.read_csv(src, keep_default_na=False, na_values=[""])
    pp["Capacity"] = pd.to_numeric(pp["Capacity"], errors="coerce")
    print(f"Year {YEAR}: {len(pp):,} tagged plants from {src.name}")

    located = gsp.tag_latlon(pp, "lat", "lon")
    located = gsp.apply_overrides(located, key_col="Name")

    methods = located["located_method"].value_counts().to_dict()
    print(f"Location method: {methods}")
    miss = located["gsp_group"].isna().sum()
    if miss:
        print(f"  WARNING: {miss} plants could not be located (no/invalid lat-lon)")

    # --- CfD register cross-check (independent gsp_group label) ---
    # Only meaningful where the Stage-1 CfD link is RELIABLE: large plants
    # (distinctive names — the offshore farms whose connection group actually
    # matters). Stage 1's keyword matcher over-matches generic names
    # ("HOUSE" -> every "...House Farm"), so small-plant "mismatches" are
    # name-matching noise, NOT geolocation errors (the spatial label from lat/lon
    # is authoritative). We list only >=CHECK_MIN_MW and summarise the rest.
    CHECK_MIN_MW = 50.0
    if "cfd_contract_id" in located.columns:
        reg = cfd_register_groups()
        cfd = located[located["cfd_contract_id"].notna()
                      & (located["cfd_contract_id"] != "MANUAL_OVERRIDE")].copy()
        cfd["reg_group"] = cfd["cfd_contract_id"].map(reg)
        chk = cfd[cfd["reg_group"].notna()]
        if len(chk):
            disagree = chk[chk["gsp_group"] != chk["reg_group"]]
            big = disagree[disagree["Capacity"] >= CHECK_MIN_MW]
            small = disagree[disagree["Capacity"] < CHECK_MIN_MW]
            print(f"\nCfD register cross-check: {(chk['gsp_group'] == chk['reg_group']).sum()}"
                  f"/{len(chk)} agree; {len(disagree)} differ "
                  f"({len(small)} are <{CHECK_MIN_MW:.0f}MW Stage-1 keyword-match noise, "
                  f"spatial label authoritative)")
            for _, r in big.sort_values("Capacity", ascending=False).iterrows():
                print(f"  CHECK >={CHECK_MIN_MW:.0f}MW: {r['Name'][:38]:38s} "
                      f"{r['Capacity']:6.0f}MW  spatial={r['gsp_group']} "
                      f"register={r['reg_group']} ({r['located_method']}) "
                      f"-> add to gsp_overrides.csv if offshore-connection")

    names = gsp.group_names()
    by = (located.groupby("gsp_group")["Capacity"].agg(["count", "sum"])
          .rename(columns={"count": "n_plants", "sum": "capacity_mw"}))
    by["capacity_mw"] = by["capacity_mw"].round(0)
    by["area"] = by.index.map(names)
    by = by.sort_values("capacity_mw", ascending=False)
    print(f"\n--- Capacity by GSP group ({by.shape[0]} groups, "
          f"{located['gsp_id'].nunique()} distinct GSP ids) ---")
    print(by.to_string())
    print(f"\nTotal located capacity: {located['Capacity'].sum()/1000:,.1f} GW")

    out = cfg.processed_dir() / f"powerplants_located_{YEAR}.csv"
    located.to_csv(out, index=False)
    print(f"\nSaved {len(located):,} located plants -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
