"""Derive empirical per-year nuclear availability from FUELHH.

UK nuclear capacity is reported at *nameplate*, but the ageing AGR fleet ran well
below it — and the troubled units (Dungeness B, Hunterston B, Hinkley Point B) sat
largely offline for *years* before their official closure dates (graphite-core
inspections). The plant roster only drops a unit at its official closure, so a single
flat availability carries phantom nuclear must-run through 2019-2022 (actual fleet
availability fell to ~0.48 in 2021, vs a flat 0.65).

This derives, per year:

    availability = mean(actual NUCLEAR generation, FUELHH) / nuclear nameplate

where the nameplate is the located-plant nuclear capacity Stage 3 uses, so
capacity x availability reproduces realized nuclear output. It stays
counterfactual-safe (still capacity x availability, not baked-in generation) and
captures both the 2020-21 outage trough and the recovery to ~0.67 once the worst
units closed (fewer but healthier reactors).

Output: data/reference/nuclear_availability_by_year.csv
        [year, availability, actual_gw, nameplate_gw]
"""

from __future__ import annotations

import sys

import pandas as pd

from gbpowerdata import config as cfg

YEARS = range(2018, 2026)


def _fuelhh_nuclear_gw() -> pd.Series:
    """Mean GB nuclear generation (GW) per calendar year, from FUELHH."""
    path = next(cfg.raw_dir().glob("fuelhh_*.csv"))
    d = pd.read_csv(path, usecols=["startTime", "fuelType", "generation"])
    n = d[d["fuelType"].str.upper() == "NUCLEAR"].copy()
    n["year"] = pd.to_datetime(n["startTime"], utc=True, errors="coerce").dt.year
    return n.groupby("year")["generation"].mean() / 1000.0


def _nameplate_gw(year: int) -> float:
    """Nuclear nameplate (GW) from the located plant roster Stage 3 reads."""
    path = cfg.processed_dir() / f"powerplants_located_{year}.csv"
    if not path.exists():
        return float("nan")  # partial run — skip this year
    df = pd.read_csv(path, keep_default_na=False, na_values=[""])
    cap = pd.to_numeric(df.loc[df["Fueltype"] == "Nuclear", "Capacity"], errors="coerce")
    return float(cap.sum()) / 1000.0


def main() -> None:
    actual = _fuelhh_nuclear_gw()
    rows = []
    for y in YEARS:
        nameplate = _nameplate_gw(y)
        act = float(actual.get(y, float("nan")))
        if not (nameplate > 0) or pd.isna(act):
            continue  # need both actual generation and a located nameplate
        rows.append({"year": y, "availability": round(act / nameplate, 3),
                     "actual_gw": round(act, 2), "nameplate_gw": round(nameplate, 2)})
    out = pd.DataFrame(rows, columns=["year", "availability", "actual_gw", "nameplate_gw"])
    if out.empty:
        print("No located plant rosters found (cold run) — Stage 3 falls back to flat 0.65.")
        return
    path = cfg.reference_dir() / "nuclear_availability_by_year.csv"
    out.to_csv(path, index=False)
    print(out.to_string(index=False))
    print(f"\nSaved -> {path}")


if __name__ == "__main__":
    sys.exit(main())
