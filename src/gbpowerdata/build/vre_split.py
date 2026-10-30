"""Metered wind split offshore / onshore by the reanalysis shape, and solar from the embedded estimate.

WHY. The panel's capacity factors (stage 2) take transmission-metered wind for offshore and NESO's embedded wind
estimate for onshore. Transmission-metered wind also holds the transmission-connected onshore farms (about 7 GW,
most of them in Scotland), so a model that multiplies each class's capacity factor by its own fleet attributes all
of that output to offshore and re-counts it when it applies the embedded onshore factor to the whole onshore
fleet. Measured for 2023: offshore 5,806 MW modelled against 7,237 MW metered (-20%), onshore 4,017 MW against
1,777 MW embedded (+126%); net wind only +9%, so the error hid in the total and showed in the composition. For a
merit-order model that prices each class's support (offshore carries the deepest negative offers, onshore the
shallowest) the composition is what matters.

METHOD. Per year, the transmission-metered wind (ESPENI, Elexon's FUELHH) is split between offshore and
transmission-connected onshore by the capacity-weighted renewables.ninja reanalysis capacity factor of each class:

    share_off(t) = C_off x cf_ninja_off(t) / [ C_off x cf_ninja_off(t) + C_ons_T x cf_ninja_ons(t) ]
    offshore(t)  = ELEX_WIND(t) x share_off(t)
    onshore(t)   = ELEX_WIND(t) x (1 - share_off(t)) + EMBEDDED_WIND(t)
    solar(t)     = EMBEDDED_SOLAR(t)

The reanalysis gives the shape (which class is windier in the half-hour), the metered series the level, so the
two classes sum to metered wind by construction and nothing is fitted to a price. C_off and C_ons are the agent
table's offshore and onshore capacities of the year; the embedded onshore capacity is implied by the embedded
series' own peak at a 0.95 capacity factor, and the rest of the onshore fleet (C_ons_T) is taken as
transmission-connected and therefore inside the metered series. The reanalysis fleet factor of a class is the mean
of its GSP groups' series (`ninja/{offshore|onshore}__{group}_{year}.csv`, from `pull.renninja_pull` on
`reference/ninja_sites_by_zone.csv`), weighted by the agents' capacity in each group. Where the denominator is zero
(both classes still) the share is the capacity share. Capacity factors are written against the agents'
capacities, so capacity x cf sums to the metered series; MW are written beside them.

Ported on 30 Oct 2026 from the research repository's scripts/build_vre_cf_corrected.py (the file it wrote to
data/reference/ is reproduced byte for byte). The further split by the wind farms' own notified output (FPN) uses
the merit-order model's farm functions and is built there, not here.

OUTPUT processed/vre_cf_corrected.csv: startTime (UTC, half-hourly), wind_offshore_cf, wind_onshore_cf, solar_cf
(rounded to 4), offshore_mw, onshore_mw, solar_mw (rounded to 1).
READ BY the merit-order model (its capacity-factor loader and the FPN split), `modelinputs`.
RUN    python -m gbpowerdata.build.vre_split [--years 2018 2025]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata import processed

OUT = "vre_cf_corrected.csv"
ESPENI = "espeni.csv"
ESP_TRANS_WIND = "ELEC_POWER_ELEX_WIND[MW](float32)"
ESP_EMB_WIND = "ELEC_POWER_NGEM_EMBEDDED_WIND_GENERATION[MW](float32)"
ESP_EMB_SOLAR = "ELEC_POWER_NGEM_EMBEDDED_SOLAR_GENERATION[MW](float32)"
ESP_TIME = "ELEC_elex_startTime[utc](datetime)"
EMBEDDED_PEAK_CF = 0.95   # the embedded onshore fleet's capacity is its peak output over this factor


def ninja_fleet_cf(kind: str, year: int, weights: pd.Series | None, ninja_dir: Path | None = None) -> pd.Series:
    """Capacity-weighted reanalysis CF across GSP groups for one technology (`kind`: offshore, onshore, solar);
    the plain mean of the groups when `weights` is None or sums to zero; empty when the year has no files."""
    ninja_dir = cfg.raw_dir() / "ninja" if ninja_dir is None else Path(ninja_dir)
    series = {}
    for f in sorted(ninja_dir.glob(f"{kind}__*_{year}.csv")):
        grp = f.name.split("__")[1].split("_")[0]
        d = pd.read_csv(f)
        d["t"] = pd.to_datetime(d["time"], utc=True, format="ISO8601")
        series[f"_{grp}"] = d.set_index("t")["cf"]
    if not series:
        return pd.Series(dtype=float)
    m = pd.DataFrame(series)
    if weights is not None:
        w = weights.reindex(m.columns).fillna(0.0)
        if w.sum() > 0:
            return (m * w).sum(axis=1) / w.sum()
    return m.mean(axis=1)


def offshore_share(cf_off: np.ndarray, cf_ons: np.ndarray, cap_off: float, cap_ons_t: float) -> np.ndarray:
    """The offshore share of transmission-metered wind in each half-hour (METHOD), the capacity share where both
    reanalysis factors are zero."""
    num = cap_off * np.asarray(cf_off, float)
    den = num + cap_ons_t * np.asarray(cf_ons, float)
    return np.where(den > 0, num / np.where(den > 0, den, 1.0), cap_off / max(cap_off + cap_ons_t, 1e-9))


def load_espeni() -> pd.DataFrame:
    """ESPENI's transmission wind, embedded wind and embedded solar (MW), indexed by UTC start time."""
    esp = pd.read_csv(cfg.raw_dir() / ESPENI, usecols=[ESP_TIME, ESP_TRANS_WIND, ESP_EMB_WIND, ESP_EMB_SOLAR])
    esp["t"] = pd.to_datetime(esp[ESP_TIME], utc=True, format="ISO8601")
    return esp.set_index("t")


def split_year(year: int, esp: pd.DataFrame) -> pd.DataFrame | None:
    """One year's split on the panel's half-hours; None when the year's panel or reanalysis files are absent."""
    try:
        m = processed.merge_drivers(year)
        ag = processed.load_year(year)["agents"]
    except FileNotFoundError:
        return None
    idx = pd.to_datetime(m["startTime"], utc=True)

    wind = ag[ag["tech"] == "Wind"]
    off = wind[wind["is_offshore"].astype(bool)]
    ons = wind[~wind["is_offshore"].astype(bool)]
    c_off = float(off["capacity_mw"].sum())
    c_ons = float(ons["capacity_mw"].sum())
    c_sol = float(ag.loc[ag["tech"] == "Solar", "capacity_mw"].sum())

    e = esp.reindex(idx)
    tw = e[ESP_TRANS_WIND].to_numpy(dtype=float)
    ew = e[ESP_EMB_WIND].to_numpy(dtype=float)
    es = e[ESP_EMB_SOLAR].to_numpy(dtype=float)

    # Embedded onshore capacity implied by its own peak output; the rest of the onshore fleet is
    # transmission-connected and therefore inside the metered series.
    c_ons_emb = float(np.nanmax(ew) / EMBEDDED_PEAK_CF)
    c_ons_t = max(c_ons - c_ons_emb, 0.0)

    w_off = off.groupby("gsp_group")["capacity_mw"].sum() if "gsp_group" in off else None
    w_ons = ons.groupby("gsp_group")["capacity_mw"].sum() if "gsp_group" in ons else None
    cf_no = ninja_fleet_cf("offshore", year, w_off).reindex(idx).ffill().bfill()
    cf_nn = ninja_fleet_cf("onshore", year, w_ons).reindex(idx).ffill().bfill()
    if cf_no.empty or cf_nn.empty:
        print(f"  {year}: no reanalysis series, skipped")
        return None

    share_off = offshore_share(cf_no.to_numpy(), cf_nn.to_numpy(), c_off, c_ons_t)
    off_mw = tw * share_off
    ons_mw = tw * (1 - share_off) + np.nan_to_num(ew)
    sol_mw = np.nan_to_num(es)

    print(f"  {year}  C_off {c_off:6.0f}  C_ons_T {c_ons_t:6.0f}  C_ons_emb {c_ons_emb:6.0f}"
          f" | mean share_off {np.nanmean(share_off):.3f}"
          f" | offshore {np.nanmean(off_mw):5.0f} onshore {np.nanmean(ons_mw):5.0f}"
          f" (stage 2: {np.nanmean(m['wind_offshore_cf']) * c_off:5.0f} / "
          f"{np.nanmean(m['wind_onshore_cf']) * c_ons:5.0f})")
    return pd.DataFrame({
        "startTime": idx,
        "wind_offshore_cf": np.clip(off_mw / max(c_off, 1e-9), 0, 1).round(4),
        "wind_onshore_cf": np.clip(ons_mw / max(c_ons, 1e-9), 0, 1).round(4),
        "solar_cf": np.clip(sol_mw / max(c_sol, 1e-9), 0, 1).round(4),
        "offshore_mw": off_mw.round(1), "onshore_mw": ons_mw.round(1),
        "solar_mw": sol_mw.round(1),
    })


def build(years: tuple[int, int] = (2018, 2025)) -> pd.DataFrame:
    """The split for every year of `years` with a panel, one row per half-hour, written to processed/."""
    esp = load_espeni()
    rows = [r for y in range(years[0], years[1] + 1) if (r := split_year(y, esp)) is not None]
    if not rows:
        raise SystemExit("vre_split: nothing built (no year with a panel and reanalysis files)")
    d = pd.concat(rows, ignore_index=True).drop_duplicates("startTime")
    out = cfg.processed_dir() / OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(out, index=False)
    print(f"wrote {out} ({len(d):,} half-hours)")
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--years", nargs=2, type=int, default=[2018, 2025], metavar=("FROM", "TO"))
    a = ap.parse_args(argv)
    build((a.years[0], a.years[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
