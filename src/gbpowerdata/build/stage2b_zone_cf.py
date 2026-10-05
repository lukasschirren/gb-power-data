"""Stage 2b — per-zone (14 GSP-group) capacity factors (LOCATIONAL, additive).

The copperplate panel uses ONE national CF series per tech (Stage 2, observed
from ESPENI). This builds a per-(tech, GSP-group) half-hourly CF from the
renewables.ninja reanalysis pulled at the per-zone representative coordinates
(src/build_zone_sites.py -> src/renninja_pull.py --sites-file ninja_sites_by_zone.csv).

Reanalysis gives the *zonal shape* (how a zone's wind/solar deviates from the
national mean) but its absolute level is model-dependent, so we reconcile: each
tech's per-zone series is scaled by a single factor so the capacity-weighted
national aggregate reproduces the validated observed national CF (Stage 2). Hence
"reanalysis shape, observed level" — aggregating the per-zone CF capacity-weighted
back to national reproduces the copperplate series (additive).

Capacity weights come from agents_{year}.csv (per tech per gsp_group). Output:
  data/processed/capacity_factors_by_zone_{year}.csv
    startTime, gsp_group, tech, cf, cf_reanalysis

CAVEAT ON `cf`. The single scale factor per tech matches the national level on the ANNUAL MEAN
only, so the zones do not add up to the observed national series half-hour by half-hour. Priced
against a clearing driven by the metered series, nearly every zone then over-captures the national
fleet (measured 29 Sep 2026), which cannot hold for zones that make up that fleet. The merit-order
model therefore reads only `cf_reanalysis` and rescales it every half-hour against the metered
national CF (meritorder.comb.zonal_cf, --vre-profile zonal). Use `cf` for annual energy, not shape.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

CFG = cfg.load_config()
YEAR = int(CFG["year"])
RES = int(CFG["resolution_minutes"])
NINJA = cfg.raw_dir() / "ninja"

START = pd.Timestamp(f"{YEAR}-01-01 00:00", tz="UTC")
END = pd.Timestamp(f"{YEAR + 1}-01-01 00:00", tz="UTC")

# tech name in this module <-> observed national CF column <-> agents.csv selector
TECHS = {
    "offshore": {"obs_col": "wind_offshore_cf", "agent_tech": "Wind", "offshore": True},
    "onshore": {"obs_col": "wind_onshore_cf", "agent_tech": "Wind", "offshore": False},
    "solar": {"obs_col": "solar_cf", "agent_tech": "Solar", "offshore": False},
}


def master_index() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq=f"{RES}min", inclusive="left", tz="UTC")


def _zone_capacities() -> pd.DataFrame:
    """Capacity (MW) per (tech, gsp_group) from the located agents — CF weights."""
    a = pd.read_csv(cfg.processed_dir() / f"agents_{YEAR}.csv")
    rows = []
    for tech, spec in TECHS.items():
        m = a["tech"] == spec["agent_tech"]
        if spec["agent_tech"] == "Wind":
            m &= a["is_offshore"].astype(bool) == spec["offshore"]
        sub = a[m]
        for zone, cap in sub.groupby("gsp_group")["capacity_mw"].sum().items():
            rows.append({"tech": tech, "gsp_group": zone, "capacity_mw": cap})
    return pd.DataFrame(rows)


def _read_site_cf(site: str, idx: pd.DatetimeIndex) -> pd.Series | None:
    """Hourly ninja CF -> half-hourly on the spine (an hour applies to both HHs)."""
    f = NINJA / f"{site}_{YEAR}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    s = df.set_index("time")["cf"].sort_index()
    return s.reindex(idx, method="ffill", limit=1)


def main() -> None:
    idx = master_index()
    sites = pd.read_csv(cfg.reference_dir() / "ninja_sites_by_zone.csv")
    caps = _zone_capacities()
    obs = pd.read_csv(cfg.processed_dir() / f"capacity_factors_{YEAR}.csv")
    obs["startTime"] = pd.to_datetime(obs["startTime"], utc=True)
    obs = obs.set_index("startTime").reindex(idx)

    frames, missing = [], []
    for _, s in sites.iterrows():
        cf = _read_site_cf(s["site"], idx)
        if cf is None:
            missing.append(s["site"])
            continue
        frames.append(pd.DataFrame({"startTime": idx, "gsp_group": s["gsp_group"],
                                    "tech": s["tech"], "cf_reanalysis": cf.values}))
    if missing:
        print(f"  WARNING: {len(missing)} site files missing for {YEAR} "
              f"(pull not finished?): {missing[:6]}{'...' if len(missing) > 6 else ''}")
    if not frames:
        sys.exit(f"No per-zone ninja files for {YEAR}; run renninja_pull --sites-file first.")
    long = pd.concat(frames, ignore_index=True)

    # --- reconcile each tech's level to the observed national CF ---
    long["cf"] = long["cf_reanalysis"]
    print(f"--- Stage 2b zone CF {YEAR}: reconcile reanalysis -> observed national level ---")
    for tech, spec in TECHS.items():
        mt = long["tech"] == tech
        if not mt.any():
            continue
        w = caps[caps["tech"] == tech].set_index("gsp_group")["capacity_mw"]
        wide = long[mt].pivot_table(index="startTime", columns="gsp_group", values="cf_reanalysis")
        ww = w.reindex(wide.columns).fillna(0.0)
        nat_re = (wide.mul(ww, axis=1).sum(axis=1) / ww.sum()) if ww.sum() > 0 else wide.mean(axis=1)
        obs_mean = obs[spec["obs_col"]].mean()
        scale = float(obs_mean / nat_re.mean()) if nat_re.mean() > 0 else 1.0
        long.loc[mt, "cf"] = (long.loc[mt, "cf_reanalysis"] * scale).clip(0, 1)
        print(f"  {tech:8s}: reanalysis nat {nat_re.mean():.3f} -> observed {obs_mean:.3f} "
              f"(scale {scale:.3f}); zones {long.loc[mt, 'gsp_group'].nunique()}")

    long["cf"] = long["cf"].round(4)
    long["cf_reanalysis"] = long["cf_reanalysis"].round(4)
    out = cfg.processed_dir() / f"capacity_factors_by_zone_{YEAR}.csv"
    long[["startTime", "gsp_group", "tech", "cf", "cf_reanalysis"]].to_csv(out, index=False)
    print(f"\nSaved {len(long):,} rows ({long['gsp_group'].nunique()} zones x "
          f"{long['tech'].nunique()} techs) -> {out.name}")


if __name__ == "__main__":
    sys.exit(main())
