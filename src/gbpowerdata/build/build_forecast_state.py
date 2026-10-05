"""Build the D-1 INFORMATION-SET table: forecast_state_{year}.csv on the half-hourly UTC spine.

For every target period t on delivery day D we keep the LATEST forecast vintage published at or before
GATE (default 09:00 UTC on D-1), per series, from the raw files written by gbpowerdata.pull.forecast_pull:

  wind_tx_fc_mw        Elexon WINDFOR (transmission-metered wind), hourly targets forward-filled to HH
  emb_wind_fc_mw,
  emb_solar_fc_mw      NESO embedded wind/solar archive, 07-09 D-1 vintages (2019-06 onward)
  dgws_won_fc_mw,
  dgws_woff_fc_mw,
  dgws_solar_fc_mw     Elexon DGWS (B1440) "Day ahead" process, published 16:45 D-1 -> AFTER the gate; kept
                       as a labelled proxy (used to backfill solar/embedded before 2019-06)
  demand_fc_mw         Elexon NDF boundary N (2021-07 onward), else NESO cardinal-point DA forecast
                       interpolated across the day (2018 onward); demand_fc_source says which
  margin_fc_mw,
  indgen_fc_mw         Elexon MELNGC / INDGEN boundary N (2021-07 onward)
  vre_fc_mw            wind_tx_fc + embedded wind + embedded solar (NESO archive, else DGWS proxy)
  resid_fc_mw          demand_fc - wind_tx_fc. NB demand_fc is on the NATIONAL-DEMAND basis (transmission
                       demand net of embedded generation, excl. station load/pumping/exports), so embedded
                       wind/solar are already netted: subtract transmission wind only (no double count).
  underlying_fc_mw     demand_fc + embedded wind + embedded solar (for VRE-share views)

Usage:  set PYTHONPATH=src && python -m gbpowerdata.build.build_forecast_state --start 2016 --end 2025
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg

RAW = cfg.raw_dir() / "forecasts"
GATE_HOUR_UTC = 9


def _spine(year: int) -> pd.DatetimeIndex:
    return pd.date_range(f"{year}-01-01", f"{year + 1}-01-01", freq="30min", tz="UTC", inclusive="left")


def _latest_pre_gate(df: pd.DataFrame, pub: str, tgt: str, val: str, gate_hour: int = GATE_HOUR_UTC) -> pd.Series:
    """Rows -> Series[target UTC] = value of the latest vintage published on D-1 at or before the gate."""
    d = df.dropna(subset=[pub, tgt, val]).copy()
    d[pub] = pd.to_datetime(d[pub], utc=True)
    d[tgt] = pd.to_datetime(d[tgt], utc=True)
    # the gate: 09:00 UTC on the local calendar day before the (local) delivery day
    d_day = d[tgt].dt.tz_convert("Europe/London").dt.normalize()
    gate = (d_day - pd.Timedelta(days=1)).dt.tz_localize(None).dt.tz_localize("UTC") + pd.Timedelta(hours=gate_hour)
    d = d[(d[pub] <= gate) & (d[pub] > gate - pd.Timedelta(hours=12))]
    d = d.sort_values(pub).groupby(tgt)[val].last()
    return d


def _read(name: str, year: int) -> pd.DataFrame | None:
    f = RAW / f"{name}_{year}.csv"
    if not f.exists() or f.stat().st_size < 50:
        return None
    return pd.read_csv(f)


def _elexon_series(name: str, year: int, val: str, spine: pd.DatetimeIndex, ffill_hourly: bool = False,
                   pre_gate: bool = True) -> pd.Series:
    """Concatenate year and previous-year raw files (D-1 publications for Jan 1 sit in the previous file)."""
    parts = [x for x in (_read(name, year - 1), _read(name, year)) if x is not None]
    if not parts:
        return pd.Series(np.nan, index=spine)
    df = pd.concat(parts, ignore_index=True)
    if pre_gate:
        s = _latest_pre_gate(df, "publishTime", "startTime", val)
    else:                                   # DGWS: 16:45 D-1 vintage, take the latest publication on D-1
        df["publishTime"] = pd.to_datetime(df["publishTime"], utc=True)
        df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
        loc_day = df["startTime"].dt.tz_convert("Europe/London").dt.normalize()
        pub_day = df["publishTime"].dt.tz_convert("Europe/London").dt.normalize()
        df = df[pub_day == loc_day - pd.Timedelta(days=1)]
        s = df.sort_values("publishTime").groupby("startTime")[val].last()
    s = s.reindex(spine.union(s.index)).sort_index()
    if ffill_hourly:
        s = s.ffill(limit=1)
    return s.reindex(spine)


def _dgws(year: int, spine: pd.DatetimeIndex) -> pd.DataFrame:
    out = pd.DataFrame(index=spine)
    parts = [x for x in (_read("DGWS", year - 1), _read("DGWS", year)) if x is not None]
    if not parts:
        for c in ("dgws_won_fc_mw", "dgws_woff_fc_mw", "dgws_solar_fc_mw"):
            out[c] = np.nan
        return out
    df = pd.concat(parts, ignore_index=True)
    df = df[df["processType"] == "Day ahead"]
    for psr, col in (("Wind Onshore", "dgws_won_fc_mw"), ("Wind Offshore", "dgws_woff_fc_mw"), ("Solar", "dgws_solar_fc_mw")):
        sub = df[df["psrType"] == psr].rename(columns={"quantity": col})
        out[col] = _elexon_series_from_df(sub, col, spine)
    return out


def _elexon_series_from_df(df: pd.DataFrame, val: str, spine: pd.DatetimeIndex) -> pd.Series:
    df = df.copy()
    df["publishTime"] = pd.to_datetime(df["publishTime"], utc=True)
    df["startTime"] = pd.to_datetime(df["startTime"], utc=True)
    loc_day = df["startTime"].dt.tz_convert("Europe/London").dt.normalize()
    pub_day = df["publishTime"].dt.tz_convert("Europe/London").dt.normalize()
    df = df[pub_day == loc_day - pd.Timedelta(days=1)]
    return df.sort_values("publishTime").groupby("startTime")[val].last().reindex(spine)


def _embedded(year: int, spine: pd.DatetimeIndex) -> pd.DataFrame:
    out = pd.DataFrame(index=spine)
    parts = [x for x in (_read("neso_embedded_da", year - 1), _read("neso_embedded_da", year)) if x is not None]
    if not parts:
        out["emb_wind_fc_mw"] = np.nan; out["emb_solar_fc_mw"] = np.nan
        return out
    df = pd.concat(parts, ignore_index=True)
    tgt = pd.to_datetime(df["DATE_GMT"].str[:10] + " " + df["TIME_GMT"].astype(str).str[:5], utc=True)
    pub = pd.to_datetime(df["Forecast_Datetime"], utc=True)          # archive timestamps are GMT
    d = pd.DataFrame({"pub": pub, "tgt": tgt, "w": df["EMBEDDED_WIND_FORECAST"], "s": df["EMBEDDED_SOLAR_FORECAST"]})
    out["emb_wind_fc_mw"] = _latest_pre_gate(d, "pub", "tgt", "w").reindex(spine)
    out["emb_solar_fc_mw"] = _latest_pre_gate(d, "pub", "tgt", "s").reindex(spine)
    return out


def _cardinal_demand(year: int, spine: pd.DatetimeIndex) -> pd.Series:
    f = RAW / "neso_da_demand_cardinal_points.csv"
    if not f.exists():
        return pd.Series(np.nan, index=spine)
    cp = pd.read_csv(f)
    cp = cp[cp["DAYSAHEAD"] == 1].copy()
    cp["target"] = pd.to_datetime(cp["TARGETDATE"].astype(str).str[:10])
    cp = cp[cp["target"].dt.year == year]
    cp["ts_issue"] = pd.to_datetime(cp["FORECAST_TIMESTAMP"], errors="coerce")
    # keep the latest issue per target day (issued on D-1); CP_ST_TIME is HHMM local clock time
    cp = cp.sort_values("ts_issue").groupby(["target", "CP_ST_TIME"], as_index=False).last()
    hh = cp["CP_ST_TIME"].astype(int) // 100; mm = cp["CP_ST_TIME"].astype(int) % 100
    naive = cp["target"] + pd.to_timedelta(hh, unit="h") + pd.to_timedelta(mm, unit="m")
    cp["t"] = naive.dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    s = cp.dropna(subset=["t"]).set_index("t")["FORECASTDEMAND"].astype(float).sort_index()
    s = s[~s.index.duplicated()]
    full = s.reindex(spine.union(s.index)).sort_index().interpolate(method="time", limit=8, limit_area="inside")
    return full.reindex(spine)


def build(year: int) -> pd.DataFrame:
    sp = _spine(year)
    out = pd.DataFrame(index=sp)
    out["wind_tx_fc_mw"] = _elexon_series("WINDFOR", year, "generation", sp, ffill_hourly=True)
    emb = _embedded(year, sp); out = out.join(emb)
    dg = _dgws(year, sp); out = out.join(dg)
    ndf = _elexon_series("NDF", year, "demand", sp)
    card = _cardinal_demand(year, sp)
    out["demand_fc_mw"] = ndf.where(ndf.notna(), card)
    out["demand_fc_source"] = np.where(ndf.notna(), "NDF", np.where(card.notna(), "NESO_CP", ""))
    out["margin_fc_mw"] = _elexon_series("MELNGC", year, "margin", sp)
    out["indgen_fc_mw"] = _elexon_series("INDGEN", year, "generation", sp)
    emb_w = out["emb_wind_fc_mw"]; emb_s = out["emb_solar_fc_mw"]
    # proxy: DGWS onshore includes embedded wind only partially; when the NESO archive is absent use DGWS solar
    # for solar and leave embedded wind to the DGWS onshore total minus nothing (flagged by vre_fc_source)
    solar = emb_s.where(emb_s.notna(), out["dgws_solar_fc_mw"])
    out["vre_fc_mw"] = out["wind_tx_fc_mw"] + emb_w.fillna(0) + solar.fillna(0)
    out["vre_fc_source"] = np.where(emb_w.notna(), "WINDFOR+NESO_EMB", np.where(solar.notna(), "WINDFOR+DGWS_SOLAR", "WINDFOR"))
    out["resid_fc_mw"] = out["demand_fc_mw"] - out["wind_tx_fc_mw"]
    out["underlying_fc_mw"] = out["demand_fc_mw"] + emb_w.fillna(0) + solar.fillna(0)
    out.index.name = "startTime"
    return out


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", type=int, default=2016)
    p.add_argument("--end", type=int, default=2025)
    a = p.parse_args(argv)
    for y in range(a.start, a.end + 1):
        df = build(y)
        out = cfg.processed_dir() / f"forecast_state_{y}.csv"
        df.to_csv(out, float_format="%.1f")
        cov = df[["wind_tx_fc_mw", "emb_wind_fc_mw", "dgws_solar_fc_mw", "demand_fc_mw", "margin_fc_mw"]].notna().mean().round(3).to_dict()
        print(f"[{y}] -> {out.name}  coverage {cov}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
