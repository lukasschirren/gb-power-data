"""Loss-of-load probability and de-rated margin per settlement period: the system operator's own
scarcity measure, as a D-1 midday view and at fixed horizons before delivery.

Why: the peak measures of the spike ABM (spikeabm.peaks; reports/text/spikeabm_evaluation_2026-
09-29.md section 4.4) define tight EVENTS by the physical state and then measure the price
response. The residual-load forecast is a demand-side proxy; the de-rated margin (available
capacity, de-rated for the probability of outage, above forecast demand) and the loss-of-load
probability derived from it are NESO's own tightness measure, computed for the imbalance price
under BSC modification P305 (Reserve Scarcity Price = VoLL x LoLP) and published by Elexon.

Sources (gbpowerdata.pull.forecast_pull):
  data/raw/forecasts/LOLPDRM_{year}.csv            publications 10:00-13:00 UTC on D-1 for every
                                                   delivery day D of the year (--datasets LOLPDRM
                                                   --window 10,13)
  data/raw/forecasts/LOLPDRM_horizons_{year}.csv   the values 12, 8, 4, 2 and 1 h before each
                                                   settlement period (source "lolp")

Vintages:
  lolp_da, drm_da_mw    the latest publication before 13:00 UK time on D-1. NESO extends the
                        forecast to the whole of D from its 12:00 publication (checked on the raw
                        files: earlier publications stop at 04:30 on D), so this is the 12:30
                        publication, ~3 h AFTER the day-ahead auctions close: a D-1 midday view,
                        not the auctions' information set.
  lolp_h{h}, drm_h{h}_mw   published h hours before the period; h = 1 is the final value used in
                        settlement, the ex-post measure.

Gotchas: LoLP is null in most 2018 rows (the de-rated margin is complete); the de-rated margin
can be negative; DST days have 46 or 50 periods (the UTC spine handles them).

Output: data/processed/lolp_drm_{year}.csv, half-hourly UTC `startTime` (the calendar year in
UTC), columns lolp_da, drm_da_mw, lolp_h12, drm_h12_mw, ..., lolp_h1, drm_h1_mw.
Read it with gbpowerdata.processed.read_lolp(year) (half-hourly) or read_lolp(year, hourly=True) (the
hourly auction product: highest LoLP and lowest margin of its two periods).

Usage: python -m gbpowerdata.build.build_lolp [--years 2018 2025]
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

HORIZONS = (12, 8, 4, 2, 1)
DA_CUTOFF_LOCAL_HOUR = 13     # publications before 13:00 UK time on D-1


def dayahead(year: int) -> pd.DataFrame:
    """lolp_da and drm_da_mw per settlement period of the year's delivery days (UTC index)."""
    fp = cfg.raw_dir() / "forecasts" / f"LOLPDRM_{year}.csv"
    d = pd.read_csv(fp, usecols=["publishTime", "startTime", "lossOfLoadProbability", "deratedMargin"])
    pub = pd.to_datetime(d["publishTime"], utc=True)
    st = pd.to_datetime(d["startTime"], utc=True)
    # compare wall-clock dates in UK time, naive, so a DST change cannot shift D-1 by an hour
    pub_l = pub.dt.tz_convert("Europe/London").dt.tz_localize(None)
    st_l = st.dt.tz_convert("Europe/London").dt.tz_localize(None)
    ok = (pub_l.dt.normalize() == st_l.dt.normalize() - pd.Timedelta(days=1)) & (pub_l.dt.hour < DA_CUTOFF_LOCAL_HOUR)
    d = d.assign(pub=pub, st=st)[ok].sort_values("pub")
    out = d.groupby("st")[["lossOfLoadProbability", "deratedMargin"]].last()
    out.columns = ["lolp_da", "drm_da_mw"]
    out.index.name = "startTime"
    return out


def horizons(year: int) -> pd.DataFrame:
    """lolp_h{h} and drm_h{h}_mw per settlement period (UTC index)."""
    fp = cfg.raw_dir() / "forecasts" / f"LOLPDRM_horizons_{year}.csv"
    d = pd.read_csv(fp, usecols=["publishTime", "startTime", "forecastHorizon", "lossOfLoadProbability", "deratedMargin"])
    d["startTime"] = pd.to_datetime(d["startTime"], utc=True)
    d = d.sort_values("publishTime").drop_duplicates(["startTime", "forecastHorizon"], keep="last")
    wide = d.pivot(index="startTime", columns="forecastHorizon", values=["lossOfLoadProbability", "deratedMargin"])
    out = pd.DataFrame(index=wide.index)
    for h in HORIZONS:
        out[f"lolp_h{h}"] = wide[("lossOfLoadProbability", h)] if ("lossOfLoadProbability", h) in wide else np.nan
        out[f"drm_h{h}_mw"] = wide[("deratedMargin", h)] if ("deratedMargin", h) in wide else np.nan
    return out


def build(year: int) -> pd.DataFrame:
    spine = pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="30min", tz="UTC", inclusive="left", name="startTime")
    out = pd.DataFrame(index=spine).join(dayahead(year)).join(horizons(year))
    fp = cfg.processed_dir() / f"lolp_drm_{year}.csv"
    out.to_csv(fp, float_format="%.6g")
    cov = out[["lolp_da", "drm_da_mw", "lolp_h1", "drm_h1_mw"]].notna().mean().round(3).to_dict()
    print(f"[{year}] -> {fp.name}  coverage {cov}", flush=True)
    return out


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", nargs=2, type=int, default=[2018, 2025])
    a = p.parse_args(argv)
    for y in range(a.years[0], a.years[1] + 1):
        build(y)


if __name__ == "__main__":
    main(sys.argv[1:])
