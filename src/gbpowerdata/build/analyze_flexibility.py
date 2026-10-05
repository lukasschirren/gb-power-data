"""Empirically characterise generation-technology flexibility from FUELHH.

Rather than assume must-run / ramp limits, we measure them from the observed
half-hourly fleet generation (Elexon FUELHH, 2018-2025): capacity factor, how
often a tech is off, how much it cycles WITHIN a day (load-following) vs over the
year (outages/seasonality), and its ramp-rate distribution.

Output (data/reference/): tech_flexibility_empirical.csv  — per-tech parameters
the ABM can read to set bid behaviour, availability de-rating, ramp and
min-stable limits.

Caveat: FUELHH is FLEET-level, not per-unit. Intraday min/max therefore measures
fleet load-following; a single unit's min-stable level is higher. The seasonal
CF variation for nuclear is availability (refuelling/outages), not economic
dispatch.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

# FUELHH fuel -> model technology label.
FUELS = {"NUCLEAR": "Nuclear", "COAL": "Hard Coal", "CCGT": "CCGT",
         "OCGT": "OCGT", "PS": "Pumped Storage"}
START, END = pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")


def load_fuelhh() -> pd.DataFrame:
    f = sorted(cfg.raw_dir().glob("fuelhh_*.csv"))[-1]
    df = pd.read_csv(f, usecols=["startTime", "fuelType", "generation"])
    df = df[df["fuelType"].isin(FUELS)].copy()
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df["generation"] = pd.to_numeric(df["generation"], errors="coerce")
    df = df[(df["startTime"] >= START) & (df["startTime"] < END)]
    return df.pivot_table(index="startTime", columns="fuelType", values="generation",
                          aggfunc="mean").sort_index()


def tech_metrics(s: pd.Series) -> dict:
    s = s.dropna()
    cap = s.quantile(0.995)
    if cap < 50:  # effectively retired in-window (e.g. oil, late coal)
        return {"cap_proxy_mw": int(round(cap)), "note": "negligible/retired"}
    run = s[s > 0.05 * cap]
    d = s.diff().dropna() * 2  # MW per hour
    daily = (pd.DataFrame({"g": run, "date": run.index.date})
             .groupby("date")["g"].agg(["min", "max"]))
    daily = daily[daily["max"] > 0]
    return {
        "cap_proxy_mw": int(round(cap)),
        "mean_cf": round(s.mean() / cap, 2),
        "pct_periods_off": round((s < 0.02 * cap).mean() * 100, 1),
        "intraday_minmax": round((daily["min"] / daily["max"]).mean(), 2),
        "min_stable_pct_committed": round((daily["min"] / daily["max"]).quantile(0.10) * 100, 0),
        "ramp_up_p95_pct_per_h": round(d[d > 0].quantile(0.95) / cap * 100, 1),
        "ramp_dn_p95_pct_per_h": round(-d[d < 0].quantile(0.05) / cap * 100, 1),
        "ramp_p99_pct_per_h": round(d.abs().quantile(0.99) / cap * 100, 1),
    }


def main() -> None:
    w = load_fuelhh()
    rows = []
    for fuel, tech in FUELS.items():
        if fuel not in w:
            continue
        m = {"fuelhh_type": fuel, "technology": tech}
        m.update(tech_metrics(w[fuel]))
        rows.append(m)
    out = pd.DataFrame(rows)
    path = cfg.reference_dir() / "tech_flexibility_empirical.csv"
    out.to_csv(path, index=False)

    print("=== Empirical tech flexibility, 2018-2025 (FUELHH fleet-level) ===")
    print(out.to_string(index=False))
    print("\nintraday_minmax ~1.0 = runs flat within the day (no load-following).")
    print("Per-year capacity factor (availability for nuclear; dispatch for the rest):")
    for fuel in ("NUCLEAR", "COAL", "CCGT"):
        if fuel not in w:
            continue
        line = f"  {fuel:8s}"
        for y in range(2018, 2026):
            s = w[fuel][w.index.year == y].dropna()
            cap = s.quantile(0.995)
            line += f" {y}:{(s.mean()/cap):.2f}" if cap > 50 else f" {y}: -- "
        print(line)
    print(f"\nSaved -> {path.name}")


if __name__ == "__main__":
    sys.exit(main())
