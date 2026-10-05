"""Stage 2c — per-zone (14 GSP-group) demand (LOCATIONAL, additive).

The copperplate panel clears ONE national demand series (Stage 2). This splits it
across the 14 GSP groups.

Granularity choice (see reports/text/gsp_locational_phase_scope.md): true metered
half-hourly demand per GSP group lives in Elexon P114 settlement data (a heavy
raw-settlement extraction). As the tractable, internally-consistent first cut we
apply the validated national half-hourly *shape* to each zone, weighted by that
zone's *share of annual demand* (data/reference/gsp_group_demand_weights.csv,
DESNZ-informed regional consumption mapped to GSP groups). Summing the per-zone
series reproduces the national demand exactly (additive). The shape is national,
not zone-specific — refine by replacing the weights with, or layering on top of,
Elexon P0276/P114 metered per-group demand.

We split GROSS demand (national_demand_mw = transmission + embedded), because in
the locational model embedded solar / onshore wind are explicit generation agents
(Stage 3) that supply into demand rather than being netted out of it.

Output: data/processed/demand_by_zone_{year}.csv
    startTime, gsp_group, demand_mw
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg

CFG = cfg.load_config()
YEAR = int(CFG["year"])


def weights() -> pd.Series:
    w = pd.read_csv(cfg.reference_dir() / "gsp_group_demand_weights.csv")
    s = w.set_index("gsp_group")["annual_gwh"].astype(float)
    return s / s.sum()


def main() -> None:
    nat = pd.read_csv(cfg.processed_dir() / f"demand_{YEAR}.csv",
                      usecols=["startTime", "national_demand_mw"])
    nat["startTime"] = pd.to_datetime(nat["startTime"], utc=True)
    w = weights()
    print(f"Year {YEAR}: splitting national demand across {len(w)} GSP groups")
    print("Weight shares (%):", (w.mul(100).round(1)).to_dict())

    frames = []
    for zone, share in w.items():
        frames.append(pd.DataFrame({
            "startTime": nat["startTime"],
            "gsp_group": zone,
            "demand_mw": (nat["national_demand_mw"] * share).round(2),
        }))
    long = pd.concat(frames, ignore_index=True)

    # additivity check
    recon = long.groupby("startTime")["demand_mw"].sum()
    err = (recon - nat.set_index("startTime")["national_demand_mw"]).abs().max()
    print(f"Additivity check: max |sum(zones) - national| = {err:.3f} MW")
    assert err < 1.0, "per-zone demand does not sum back to national"

    out = cfg.processed_dir() / f"demand_by_zone_{YEAR}.csv"
    long.to_csv(out, index=False)
    print(f"Saved {len(long):,} rows ({long['gsp_group'].nunique()} zones x "
          f"{len(nat):,} periods) -> {out.name}")
    print("\nMean demand by zone (GW):")
    print(long.groupby("gsp_group")["demand_mw"].mean().div(1000).round(2).sort_values(ascending=False).to_string())


if __name__ == "__main__":
    sys.exit(main())
