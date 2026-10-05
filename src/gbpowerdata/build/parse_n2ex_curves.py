"""Reduce the raw N2EX aggregate bid curves to compact per-hour features.

The raw curves (`data/raw/nordpool/curves/{date}.json`, ~12 GB over 2016-2025) are
too large to use directly. For each delivery hour this extracts:

  * the price-insensitive supply block -- volume offered at the -£500 floor and at £0
    (a proxy for must-run + subsidised generation that bids in regardless of price);
  * the demand-curve price sensitivity and, anchored on the ACTUAL N2EX cleared
    price, the price the auction WOULD reach if CfD-backed (and, separately, ALL
    variable-renewable) generation were removed -- the auction-price *suppression*
    attributable to subsidised renewables (the merit-order effect).

Method. The published aggregate curves EXCLUDE block orders, so reconstructing the
clearing price from supply==demand overshoots at peak. We therefore do NOT rely on a
from-scratch clearing for the headline; instead we anchor on the real N2EX price `p0`
and read the merit-order effect off the DEMAND curve (block-order-free and the side
that captures buyers' inelasticity): removing R MW of floor-bidding renewable supply
means R less is cleared, so the price rises to `Dinv(q0 - R)`, where `q0 = D(p0)`.
This is a demand-side estimate (an upper bound on the effect, since it ignores
re-dispatch of other supply); it is cross-checked against the empirical
price-vs-wind slope in notebook 02. A naive supply==demand clearing is also kept,
purely to show (in nb 06) where it diverges from N2EX.

The curves are anonymous (no CfD tag), so CfD impact is *inferred* by removing the
CfD-backed renewable VOLUME (capacity x capacity-factor) from the cleared volume.

Output: `data/processed/n2ex_curve_features_{year}.csv` (one row per delivery hour).

Usage:  python -m gbpowerdata.build.parse_n2ex_curves 2023            # one year
        python -m gbpowerdata.build.parse_n2ex_curves 2018 2025       # inclusive range
        python -m gbpowerdata.build.parse_n2ex_curves                 # all years with curves
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

CURVES = cfg.raw_dir() / "nordpool" / "curves"


def _is_true(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().eq("true")


def hourly_generation(year: int) -> pd.DataFrame:
    """Hourly VRE and CfD-VRE generation (MW). Mirrors notebooks/_eda.vre_generation:
    transmission wind = wind_offshore_cf x offshore capacity, plus actual embedded
    wind & solar. CfD-VRE uses only CfD wind/solar capacity (the floor-bidding ones;
    CfD biomass has real fuel cost and is excluded)."""
    pdir = cfg.processed_dir()
    dem = pd.read_csv(pdir / f"demand_{year}.csv")
    cf = pd.read_csv(pdir / f"capacity_factors_{year}.csv")
    ag = pd.read_csv(pdir / f"agents_{year}.csv")
    for df in (dem, cf):
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    m = dem.merge(cf, on="startTime")

    wind = ag[ag["tech"] == "Wind"]
    off_cap = wind.loc[_is_true(wind["is_offshore"]), "capacity_mw"].sum()
    cfd = ag[ag["support_regime"] == "CfD"]
    cfd_w = cfd[cfd["tech"] == "Wind"]
    cfd_off = cfd_w.loc[_is_true(cfd_w["is_offshore"]), "capacity_mw"].sum()
    cfd_on = cfd_w.loc[~_is_true(cfd_w["is_offshore"]), "capacity_mw"].sum()
    cfd_sol = cfd.loc[cfd["tech"] == "Solar", "capacity_mw"].sum()

    m["vre"] = m["wind_offshore_cf"] * off_cap + m["embedded_wind_mw"] + m["embedded_solar_mw"]
    m["cfd_vre"] = (m["wind_offshore_cf"] * cfd_off + m["wind_onshore_cf"] * cfd_on
                    + m["solar_cf"] * cfd_sol)
    return m.set_index("startTime")[["vre", "cfd_vre"]].resample("h").mean()


def _invert_inc(x: np.ndarray, y: np.ndarray, target: float) -> float:
    """Inverse of an increasing step function: smallest y where x(y) crosses target."""
    i = int(np.searchsorted(x, target))
    if i <= 0:
        return float(y[0])
    if i >= len(x):
        return float(y[-1])
    x0, x1, y0, y1 = x[i - 1], x[i], y[i - 1], y[i]
    return float(y1 if x1 == x0 else y0 + (target - x0) * (y1 - y0) / (x1 - x0))


def n2ex_prices_hourly() -> pd.Series:
    """Actual N2EX day-ahead cleared price, hourly UTC (the anchor + ground truth)."""
    f = next((cfg.raw_dir() / "nordpool").glob("n2ex_prices_n2ex_*.csv"))
    px = pd.read_csv(f)
    px["deliveryStart"] = pd.to_datetime(px["deliveryStart"], utc=True)
    return px.set_index("deliveryStart")["price"].sort_index()


def features(supply: list, demand: list, p0: float, r_vre: float, r_cfd: float,
             h: float = 15.0) -> dict:
    sp = np.array([p["price"] for p in supply], float)
    sv = np.array([p["volume"] for p in supply], float)
    dp = np.array([p["price"] for p in demand], float)
    dv = np.array([p["volume"] for p in demand], float)
    so, do = np.argsort(sp), np.argsort(dp)
    sp, sv, dp, dv = sp[so], sv[so], dp[do], dv[do]

    def S(p):
        return float(np.interp(p, sp, sv))

    def D(p):
        return float(np.interp(p, dp, dv))

    # Local slopes (MW per £) around the actual price. The merit-order effect of
    # removing R MW of floor-bidding renewable supply is R / (S' + |D'|): both the
    # supply re-stack (gas plants step in) and demand response absorb the shortfall.
    s_slope = (S(p0 + h) - S(p0 - h)) / (2 * h)
    d_slope = (D(p0 + h) - D(p0 - h)) / (2 * h)
    denom = s_slope + abs(d_slope)          # net responsiveness, MW per £
    ok = denom > 1.0

    # Naive supply==demand clearing (EXCLUDES block orders) -- kept only for the
    # methodological caveat figure in notebook 06.
    grid = np.unique(np.concatenate([sp, dp]))
    diff = np.interp(grid, sp, sv) - np.interp(grid, dp, dv)
    naive = _invert_inc(diff, grid, 0.0)

    return {
        "n2ex_price": p0,
        "cleared_volume_mw": D(p0),
        "naive_clearing_price": naive,
        "supply_floor_mw": float(sv[0]),
        "supply_at_0_mw": S(0.0),
        "supply_slope_mw_per_gbp": s_slope,
        "demand_slope_mw_per_gbp": abs(d_slope),
        "sensitivity_gbp_per_gw": 1000.0 / denom if ok else np.nan,
        "suppression_cfd": r_cfd / denom if ok else np.nan,
        "suppression_vre": r_vre / denom if ok else np.nan,
    }


def build(year: int) -> None:
    gen = hourly_generation(year)
    px = n2ex_prices_hourly()
    files = sorted(CURVES.glob(f"{year}-*.json"))
    if not files:
        print(f"  {year}: no curve files, skipping")
        return
    rows = []
    for fp in files:
        data = json.loads(fp.read_text(encoding="utf-8"))
        for per in data.get("orderPositions", []):
            ts = pd.to_datetime(per["deliveryStart"], utc=True)
            if ts not in gen.index or ts not in px.index:
                continue
            r_vre, r_cfd, p0 = gen.at[ts, "vre"], gen.at[ts, "cfd_vre"], px.at[ts]
            if not (np.isfinite(r_vre) and np.isfinite(p0)):
                continue
            rec = features(per["supplyCurve"], per["demandCurve"], float(p0), r_vre, r_cfd)
            rec["deliveryStart"] = ts
            rec["vre_gen_mw"], rec["cfd_vre_gen_mw"] = r_vre, r_cfd
            rows.append(rec)

    df = pd.DataFrame(rows).sort_values("deliveryStart")
    cols = ["deliveryStart", "n2ex_price", "cleared_volume_mw", "naive_clearing_price",
            "supply_floor_mw", "supply_at_0_mw", "supply_slope_mw_per_gbp",
            "demand_slope_mw_per_gbp", "sensitivity_gbp_per_gw", "vre_gen_mw",
            "cfd_vre_gen_mw", "suppression_cfd", "suppression_vre"]
    df = df[cols]
    out = cfg.processed_dir() / f"n2ex_curve_features_{year}.csv"
    df.to_csv(out, index=False)
    print(f"  {year}: {len(df):,} h | N2EX mean £{df['n2ex_price'].mean():.1f} "
          f"| floor block {df['supply_floor_mw'].mean():.0f} MW "
          f"| sens £{df['sensitivity_gbp_per_gw'].median():.2f}/GW "
          f"| CfD suppression median £{df['suppression_cfd'].median():.2f}/MWh -> {out.name}")


def main(argv: list[str]) -> None:
    if len(argv) == 1:
        years = sorted({int(p.stem.split("-")[0]) for p in CURVES.glob("*.json")})
    elif len(argv) == 2:
        years = [int(argv[1])]
    else:
        years = list(range(int(argv[1]), int(argv[2]) + 1))
    print(f"Parsing N2EX curve features for {years}")
    for y in years:
        build(y)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
