"""Loaders for the pipeline's per-year processed tables (data/processed/*_{year}.csv).

They belong to the data layer: every model, figure script or notebook that consumes the
pipeline's outputs should read them through here, so the file naming and the UTC parsing live
in ONE place.

    load_year(2023)      -> {"demand": df, "cf": df, "fuel": df, "mid": df, "agents": df, ...}
    merge_drivers(2023)  -> half-hourly join of demand + capacity factors + fuel prices + MID,
                            plus the monthly coal price mapped onto the index

Nothing here carries model economics: the coal fallback price is a parameter, not a constant.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg

# friendly file-kind -> processed/{prefix}_{year}.csv
KIND_FILE = {
    "demand": "demand", "cf": "capacity_factors", "fuel": "fuel_prices",
    "mid": "mid_target", "agents": "agents", "regime": "regime_summary",
    "fleet": "cfd_fleet", "plants": "powerplants_tagged",
}
TS_KINDS = ("demand", "cf", "fuel", "mid")  # parse startTime as UTC

COAL_FALLBACK_GBP_MWH_TH = 40.0  # used only when data/raw/coal_monthly.csv is absent


def years_available() -> list[int]:
    """Years for which the timeseries were built, sorted ascending."""
    # demand_{year}.csv only - NOT demand_by_zone_{year}.csv (the locational file).
    return sorted(int(p.stem.split("_")[-1])
                  for p in cfg.processed_dir().glob("demand_[0-9][0-9][0-9][0-9].csv"))


def processed_csv(kind: str, year: int | None = None) -> Path:
    """Path to a processed file. ``year=None`` only valid for panel files."""
    if kind == "cfd_status":
        return cfg.processed_dir() / "cfd_status.csv"
    return cfg.processed_dir() / f"{KIND_FILE[kind]}_{year}.csv"


def read_kind(kind: str, year: int) -> pd.DataFrame:
    df = pd.read_csv(processed_csv(kind, year))
    if kind in TS_KINDS:
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    return df


def read_lolp(year: int, hourly: bool = False) -> pd.DataFrame:
    """NESO's loss-of-load probability and de-rated margin (gbpowerdata.build.build_lolp), half-hourly
    and indexed by UTC `startTime`. `hourly=True` gives the hourly auction product: the highest
    LoLP and the lowest de-rated margin of its two settlement periods. Kept out of KIND_FILE so
    load_year() does not require it for years before the P305 series was pulled."""
    df = pd.read_csv(cfg.processed_dir() / f"lolp_drm_{year}.csv")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df.set_index("startTime").sort_index()
    if not hourly:
        return df
    r = df.resample("h")
    return pd.concat([r[[c for c in df.columns if c.startswith("lolp")]].max(),
                      r[[c for c in df.columns if c.startswith("drm")]].min()], axis=1)[df.columns]


def read_system_prices(year: int, hourly: bool = False) -> pd.DataFrame:
    """The cash-out price and net imbalance volume (gbpowerdata.build.build_system_prices), half-hourly
    and indexed by UTC `startTime`. `hourly=True` gives the hourly product: the mean of the two
    periods' prices and the sum of their volumes (an hour with one period missing keeps the other;
    the derivation code is dropped). Kept out of KIND_FILE, like read_lolp, so load_year() does
    not require it."""
    df = pd.read_csv(cfg.processed_dir() / f"system_prices_{year}.csv")
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    df = df.set_index("startTime").sort_index()
    if not hourly:
        return df
    prices = [c for c in df.columns if c.endswith("_gbp_per_mwh")]
    volumes = [c for c in df.columns if c.endswith("_mwh") and c not in prices]
    r = df.resample("h")
    return pd.concat([r[prices].mean(), r[volumes].sum(min_count=1)], axis=1)[prices + volumes]


def load_year(year: int) -> dict[str, pd.DataFrame]:
    """All per-year tables for one year, keyed by friendly name."""
    return {k: read_kind(k, year) for k in KIND_FILE}


def load_panel(kind: str, years: list[int] | None = None) -> pd.DataFrame:
    """One long DataFrame across years with an added ``year`` column."""
    years = years or years_available()
    frames = []
    for y in years:
        df = read_kind(kind, y)
        df.insert(0, "year", y)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def load_cfd_status() -> pd.DataFrame:
    df = pd.read_csv(processed_csv("cfd_status"))
    for c in ("cfd_start_date", "cfd_end_date", "commissioned_date"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def coal_price_thermal(times: pd.Series, fallback: float = COAL_FALLBACK_GBP_MWH_TH) -> pd.Series:
    """Monthly GB coal price (GBP/MWh-thermal, gbpowerdata.pull.coal_pull) mapped to the
    half-hourly index; falls back to a flat value if the series is absent."""
    path = cfg.raw_dir() / "coal_monthly.csv"
    if not path.exists():
        return pd.Series(fallback, index=times.index)
    cm = pd.read_csv(path).set_index("month")["coal_gbp_per_mwh_thermal"]
    return (times.dt.strftime("%Y-%m").map(cm)
            .astype(float).ffill().bfill()
            .fillna(fallback))


def merge_drivers(year: int, coal_fallback: float = COAL_FALLBACK_GBP_MWH_TH) -> pd.DataFrame:
    """Half-hourly join of demand + capacity factors + fuel prices + MID price,
    plus the monthly coal price mapped onto the index."""
    d = load_year(year)
    m = (d["demand"]
         .merge(d["cf"], on="startTime")
         .merge(d["fuel"], on="startTime")
         .merge(d["mid"], on="startTime"))
    m["coal_price_gbp_per_mwh_thermal"] = coal_price_thermal(m["startTime"], coal_fallback)
    return m
