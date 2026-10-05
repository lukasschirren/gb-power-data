"""Pull per-unit Maximum Export Limits (Elexon MELS) and physical notifications (PN) for chosen days
-> data/raw/mels/MELS_{date}.csv and PN_{date}.csv (and, for the units of interest, their Balancing
Mechanism bid-offer pairs, BOD_{date}.csv).

A unit's MEL is the most it declares it can export in a settlement period: its availability as the
unit itself states it to NESO, revisable up to real time. Paired with its Final Physical Notification
(dataset PN, pulled here for the same units and window so both cover the same fleet; the MW the unit
plans to generate at gate closure), it separates three states of a unit in an
hour: running (FPN > 0), available but idle (MEL > 0, FPN = 0), and unavailable (MEL = 0). That is the
plant-level test of whether capacity missing from the day-ahead books in a price spike was sold
elsewhere (running) or held back (available and idle); reports/text/peak_prices_explained_2026-09-30.md,
section 2, figure 10 (scripts/fig_shell/fig_peaks_explained.units()). A unit's first BOD offer pair is the
price at which it would raise output in the Balancing Mechanism, for an idle unit the price to start.

Source: Elexon Insights /datasets/{MELS,PN,BOD}/stream (free, no key), filtered by bmUnit in batches of
BATCH units so a request stays small (all units for one hour is ~2 MB; 60 units ~50 KB). Every
MEL notification is kept (notificationTime, notificationSequence); load() keeps the last one per unit
and settlement period. Days are fetched for a UTC window (default 06:00-23:00, the GB morning and evening
peaks in GMT and BST; price spikes also fall in the morning). Cached per day; an existing day file is
skipped, so the window of a cache must not change (delete the folder to re-pull).

Units: transmission BM units of the fuel types in FUELS from the newest BM-unit register, plus the
battery units of that register (spikeabm.population.is_battery_unit's naming rule, re-stated here so
gbpowerdata does not import spikeabm).

Usage (from code):  pull_days(["2025-01-08", ...]);   CLI:  python -m gbpowerdata.pull.mels_pull 2025-01-08 2025-01-09
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg

STREAMS = {"MELS": "https://data.elexon.co.uk/bmrs/api/v1/datasets/MELS/stream",
           "PN": "https://data.elexon.co.uk/bmrs/api/v1/datasets/PN/stream",
           "BOD": "https://data.elexon.co.uk/bmrs/api/v1/datasets/BOD/stream"}
OUT = cfg.raw_dir() / "mels"
FUELS = ("CCGT", "OCGT", "COAL", "BIOMASS", "PS", "NPSHYD", "NUCLEAR", "OIL")
BATCH = 80
KEEP = ["bmUnit", "settlementDate", "settlementPeriod", "timeFrom", "timeTo", "levelFrom", "levelTo",
        "notificationTime", "notificationSequence"]


def _is_battery(unit: str, name: str, party: str) -> bool:
    """The battery rule of spikeabm.population: the unit code's type letter is B (the letter before
    the trailing number, as in E_ARBRB-1), or the name or lead party says battery or storage."""
    import re
    code = re.sub(r"^[A-Z0-9]+_+", "", str(unit))
    m = re.search(r"([A-Za-z])-?\d+$", code)
    text = f"{name} {party}".upper()
    return (m is not None and m.group(1).upper() == "B") or any(k in text for k in ("BATT", "BESS", "STORAGE"))


def units() -> pd.DataFrame:
    """BM units in scope with their group (fuel type, or BATTERY)."""
    reg = sorted(cfg.raw_dir().glob("bm_units_*.csv"))[-1]
    b = pd.read_csv(reg)
    b["unit"] = b["elexonBmUnit"].astype(str)
    th = b[b["unit"].str.startswith("T_") & b["fuelType"].isin(FUELS)].assign(group=lambda d: d["fuelType"])
    other = b[b["fuelType"].isin(["OTHER"]) | b["fuelType"].isna()]
    bat = other[[_is_battery(u, str(n), str(p)) for u, n, p in zip(other["unit"], other["bmUnitName"], other["leadPartyName"])]]
    bat = bat.assign(group="BATTERY")
    keep = pd.concat([th, bat])[["unit", "group", "generationCapacity"]].drop_duplicates("unit")
    return keep.reset_index(drop=True)


def _get(params: dict, dataset: str = "MELS", tries: int = 5) -> list[dict]:
    for k in range(tries):
        try:
            r = requests.get(STREAMS[dataset], params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** k)
    raise RuntimeError(f"MELS request failed: {params.get('from')}")


def pull_days(days: list[str], window: tuple[int, int] = (6, 23), sleep_s: float = 0.2,
              dataset: str = "MELS", only: list[str] | None = None) -> list[Path]:
    """Cache `dataset` for the units in scope: MELS, PN (the final physical notification) or BOD (the
    bid-offer pairs each unit submits to the Balancing Mechanism, one row per pair and period).
    `only` narrows the units (BOD is large; the check needs it for the gas fleet only)."""
    OUT.mkdir(parents=True, exist_ok=True)
    u = units()["unit"].tolist() if only is None else list(only)
    paths = []
    for d in sorted(set(days)):
        out = OUT / f"{dataset}_{d}.csv"
        paths.append(out)
        if out.exists():
            continue
        rows: list[dict] = []
        for i in range(0, len(u), BATCH):
            rows += _get({"from": f"{d}T{window[0]:02d}:00Z", "to": f"{d}T{window[1]:02d}:00Z", "bmUnit": u[i:i + BATCH]},
                         dataset)
            time.sleep(sleep_s)
        df = pd.DataFrame(rows)
        keep = KEEP + (["pairId", "offer", "bid"] if dataset == "BOD" else [])
        df = df[[c for c in keep if c in df.columns]] if len(df) else pd.DataFrame(columns=keep)
        tmp = out.with_suffix(".part.csv")
        df.to_csv(tmp, index=False)
        tmp.replace(out)
        print(f"  {dataset} {d}: {len(df)} rows, {df['bmUnit'].nunique() if len(df) else 0} units", flush=True)
    return paths


def load(days: list[str], dataset: str = "MELS") -> pd.DataFrame:
    """The final level per unit and settlement period (the last notification), MW, for the cached days:
    the MEL (its maximum of the period) or the FPN (the mean of the period's start and end levels)."""
    fr = [pd.read_csv(OUT / f"{dataset}_{d}.csv") for d in sorted(set(days)) if (OUT / f"{dataset}_{d}.csv").exists()]
    m = pd.concat(fr, ignore_index=True)
    if "notificationTime" in m.columns:
        m = m.sort_values(["bmUnit", "timeFrom", "notificationTime", "notificationSequence"])
        # the last notification for each period overrides the earlier ones
        last = m.groupby(["bmUnit", "settlementDate", "settlementPeriod"])["notificationTime"].transform("max")
        m = m[m["notificationTime"] == last]
    col = "mel_mw" if dataset == "MELS" else "fpn_mw"
    m[col] = m[["levelFrom", "levelTo"]].max(axis=1) if dataset == "MELS" else m[["levelFrom", "levelTo"]].mean(axis=1)
    m["t"] = pd.to_datetime(m["timeFrom"], utc=True)
    # a period can hold several segments; keep the period's level as the max (MEL) or mean (FPN)
    m["sp_t"] = m["t"].dt.floor("30min")
    agg = "max" if dataset == "MELS" else "mean"
    return m.groupby(["bmUnit", "sp_t"])[col].agg(agg).reset_index().rename(columns={"sp_t": "t"})


if __name__ == "__main__":
    pull_days(sys.argv[1:])
