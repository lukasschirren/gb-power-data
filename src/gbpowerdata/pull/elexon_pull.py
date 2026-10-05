"""Pull GB electricity time series from the BMRS Elexon API into data/raw/.

This is the one pipeline source that is freely API-pullable (no key, no auth).
Everything else (ESPENI, powerplantmatching, the CfD/RO registers, gas, carbon)
is a manual download and lives in data/raw/ as a curated snapshot.

Datasets:
  MID      — Market Index Data (day-ahead clearing price, GBP/MWh) — validation target
  FUELHH   — Half-hourly generation outturn by fuel type (MW)
  ITSDO    — Initial Transmission System Demand Out-turn (MW)
  INDO     — Initial National Demand Out-turn (half-hourly, MW): the outturn of the NDF forecast
  INDOD    — Indicated National Demand Out-turn (daily aggregate, MW)
  BMUNITS  — BM Units reference list (current snapshot)

Gotchas (already handled below):
  - /datasets/{name} endpoints need `publishDateTimeFrom`/`publishDateTimeTo`.
    Plain `from`/`to` are silently ignored and only the latest row is returned.
  - The MID endpoint /balancing/pricing/market-index is the exception — it
    accepts `from`/`to` directly. We use it instead of /datasets/MID.
  - For 2022+ the N2EXMIDP feed reports price=0, volume=0 everywhere. Default
    to APXMIDP (EPEX SPOT GB).
  - INDOD is daily-aggregate — no startTime/settlementPeriod columns.

Usage:
  python -m gbpowerdata.pull.elexon_pull                                   # all datasets, default window
  python -m gbpowerdata.pull.elexon_pull mid fuelhh                        # selected datasets
  python -m gbpowerdata.pull.elexon_pull --start 2016-01-01 --end 2026-01-01   # explicit window (end exclusive)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
# repo/data/raw via the config, as every other puller: the previous relative path dated from
# when this module was src/elexon_pull.py and wrote to src/gbpowerdata/data/raw once it was moved
RAW_DIR = cfg.raw_dir()
RAW_DIR.mkdir(parents=True, exist_ok=True)

# Default window: 2016-01-01 .. 2026-01-01 (i.e. 2016 through end of 2025; end exclusive).
DEFAULT_START = datetime(2016, 1, 1, tzinfo=timezone.utc)
DEFAULT_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
CHUNK_DAYS = 7
SLEEP_S = 0.5


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _get(url: str, params: dict, timeout: int = 60) -> dict | list:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_dataset(dataset: str, start: datetime, end: datetime,
                  extra_params: dict | None = None) -> pd.DataFrame:
    """Fetch a single window from /datasets/{dataset}."""
    params = {
        "publishDateTimeFrom": start.strftime("%Y-%m-%dT%H:%MZ"),
        "publishDateTimeTo": end.strftime("%Y-%m-%dT%H:%MZ"),
        "format": "json",
    }
    if extra_params:
        params.update(extra_params)
    payload = _get(f"{BASE_URL}/datasets/{dataset}", params)
    data = payload["data"] if isinstance(payload, dict) and "data" in payload else payload
    return pd.DataFrame(data)


def fetch_dataset_range(dataset: str, start: datetime, end: datetime,
                        extra_params: dict | None = None,
                        dedup_subset: list[str] | None = None) -> pd.DataFrame:
    frames = []
    cursor = start
    while cursor < end:
        window_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        print(f"[{dataset}] {cursor.date()} -> {window_end.date()}", flush=True)
        df = fetch_dataset(dataset, cursor, window_end, extra_params=extra_params)
        if not df.empty:
            frames.append(df)
        cursor = window_end
        time.sleep(SLEEP_S)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    if dedup_subset:
        out = out.drop_duplicates(subset=dedup_subset)
    if "startTime" in out.columns:
        out["startTime"] = pd.to_datetime(out["startTime"], utc=True)
        out = out.sort_values("startTime").reset_index(drop=True)
    return out


def fetch_mid_window(start: datetime, end: datetime,
                     providers: tuple[str, ...] = ("APXMIDP",)) -> pd.DataFrame:
    """MID uses its own endpoint that accepts from/to."""
    params = {
        "from": start.strftime("%Y-%m-%dT%H:%MZ"),
        "to": end.strftime("%Y-%m-%dT%H:%MZ"),
        "format": "json",
    }
    if providers:
        params["dataProviders"] = list(providers)
    payload = _get(f"{BASE_URL}/balancing/pricing/market-index", params)
    return pd.DataFrame(payload.get("data", []))


def fetch_mid_range(start: datetime, end: datetime,
                    providers: tuple[str, ...] = ("APXMIDP",)) -> pd.DataFrame:
    frames, cursor = [], start
    while cursor < end:
        window_end = min(cursor + timedelta(days=CHUNK_DAYS), end)
        print(f"[MID] {cursor.date()} -> {window_end.date()}", flush=True)
        df = fetch_mid_window(cursor, window_end, providers=providers)
        if not df.empty:
            frames.append(df)
        cursor = window_end
        time.sleep(SLEEP_S)

    if not frames:
        return pd.DataFrame()
    out = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["startTime", "dataProvider",
                                 "settlementDate", "settlementPeriod"])
    )
    out["startTime"] = pd.to_datetime(out["startTime"], utc=True)
    return out.sort_values("startTime").reset_index(drop=True)


def save_csv(df: pd.DataFrame, name: str, start: datetime, end: datetime) -> Path:
    path = RAW_DIR / f"{name}_{start:%Y%m%d}_{end:%Y%m%d}.csv"
    df.to_csv(path, index=False)
    print(f"  Saved {len(df):,} rows -> {path}", flush=True)
    return path


def pull_mid(start: datetime, end: datetime,
             providers: tuple[str, ...] = ("APXMIDP",)) -> pd.DataFrame:
    df = fetch_mid_range(start, end, providers=providers)
    nonzero = (df["price"] != 0).sum() if "price" in df.columns else 0
    print(f"  Non-zero price rows: {nonzero:,} / {len(df):,}", flush=True)
    tag = "_".join(p.lower().replace("midp", "") for p in providers)
    save_csv(df, f"mid_{tag}", start, end)
    return df


def pull_fuelhh(start: datetime, end: datetime) -> pd.DataFrame:
    df = fetch_dataset_range("FUELHH", start, end,
                             dedup_subset=["startTime", "fuelType"])
    save_csv(df, "fuelhh", start, end)
    return df


def pull_itsdo(start: datetime, end: datetime) -> pd.DataFrame:
    df = fetch_dataset_range("ITSDO", start, end, dedup_subset=["startTime"])
    save_csv(df, "itsdo", start, end)
    return df


def pull_indo(start: datetime, end: datetime) -> pd.DataFrame:
    """INDO is the half-hourly national demand outturn on the basis of the NDF day-ahead forecast
    (transmission demand net of station load, pumping and exports), so NDF - INDO is the demand
    forecast error."""
    df = fetch_dataset_range("INDO", start, end, dedup_subset=["startTime"])
    save_csv(df, "indo", start, end)
    return df


def pull_indod(start: datetime, end: datetime) -> pd.DataFrame:
    df = fetch_dataset_range("INDOD", start, end, dedup_subset=["settlementDate"])
    save_csv(df, "indod", start, end)
    return df


def pull_bmunits(start: datetime, end: datetime) -> pd.DataFrame:
    """BM Units reference list — current snapshot; date args ignored."""
    payload = _get(f"{BASE_URL}/reference/bmunits/all", params={})
    df = pd.DataFrame(payload)
    today = datetime.now(timezone.utc).date()
    path = RAW_DIR / f"bm_units_{today:%Y%m%d}.csv"
    df.to_csv(path, index=False)
    print(f"  Saved {len(df):,} BM units -> {path}", flush=True)
    return df


PULLERS = {
    "mid": pull_mid,
    "fuelhh": pull_fuelhh,
    "itsdo": pull_itsdo,
    "indo": pull_indo,
    "indod": pull_indod,
    "bmunits": pull_bmunits,
}


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        description="Pull GB electricity time series from the BMRS Elexon API.")
    parser.add_argument("datasets", nargs="*",
                        help=f"datasets to pull (default: all). Choose from {list(PULLERS)}.")
    parser.add_argument("--start", type=_parse_date, default=DEFAULT_START,
                        help="UTC start date YYYY-MM-DD, inclusive (default: 2016-01-01).")
    parser.add_argument("--end", type=_parse_date, default=DEFAULT_END,
                        help="UTC end date YYYY-MM-DD, exclusive (default: 2026-01-01).")
    args = parser.parse_args(argv[1:])

    targets = [t.lower() for t in args.datasets] or list(PULLERS)
    unknown = [t for t in targets if t not in PULLERS]
    if unknown:
        sys.exit(f"Unknown dataset(s): {unknown}. Choose from {list(PULLERS)}.")

    print(f"Window: {args.start.date()} -> {args.end.date()}  (UTC)  out={RAW_DIR}", flush=True)
    for t in targets:
        print(f"\n=== {t.upper()} ===", flush=True)
        PULLERS[t](args.start, args.end)


if __name__ == "__main__":
    main(sys.argv)
