"""Pull the DAY-AHEAD INFORMATION SET: the forecasts market participants had at the D-1 gate.

Why: the spike ABM (reports/text/spike_abm_direction_2026-09-09.md) maps the public D-1 state to
the offered curve. The repo only held OUTTURNS; this module pulls the D-1 forecast VINTAGES.

Sources and vintages (all times UTC; GB DA auctions gate ~09:20-09:50 UK time on D-1):
  Elexon Insights  /datasets/{name}?publishDateTimeFrom&publishDateTimeTo   (no key needed)
    WINDFOR  transmission-metered wind forecast, published 8x/day; history from 2016 (196 rows/day).
    DGWS     B1440 day-ahead wind+solar generation forecast (psrType Wind Onshore/Offshore/Solar),
             processType "Day ahead" published 16:45 on D-1 (AFTER the DA gate: a proxy for the morning
             view, not the information set itself); history from 2016 (144 rows/day). Window 16-18.
    NESO embedded archive (2019-): hourly-updated embedded wind+solar forecast; we keep the 07-09 D-1
             vintages via datastore SQL -> the proper morning embedded view (see pull_neso_embedded).
    NDF      national demand forecast (boundary N), half-hourly, published ~2x/hour; history from
             2021-07 only (Insights platform start).
    MELNGC   generating-plant demand margin forecast by boundary (N = national); same history as NDF.
    INDGEN   indicated generation by boundary (N = national); same history as NDF.
    LOLPDRM  loss-of-load probability and de-rated margin (MW) per settlement period, computed by
             NESO for the imbalance price under BSC modification P305 (Reserve Scarcity Price =
             VoLL x LoLP). The indicative publication at 12:00 UK time on D-1 covers the rest of D-1,
             all of D and D+1 to 04:30 (checked 2026-09-29), so window 10-13 UTC catches it in GMT
             and BST; it comes ~2.5 h AFTER the DA gate, i.e. a D-1 midday view. History from 2018.
  For each dataset and each delivery day D we request the publications inside a window on D-1
  (default 06:00-09:00 UTC) and keep ALL rows; the build step picks the latest vintage per target
  period. Raw CSVs are per (dataset, year) and resumable: an existing file is skipped, except the
  current year's, which stops at today and is pulled again in full on every run.
  Elexon Insights  /forecast/system/loss-of-load?from&to  (at most 7 days per request)
    the LOLPDRM values at forecastHorizon 12, 8, 4, 2 and 1 hours before each settlement period;
    the 1-hour value is the final one used in settlement (the ex-post scarcity measure).
  NESO data portal (CKAN datastore): "Historic Day Ahead Demand Forecasts" — cardinal-point
    day-ahead national demand forecasts with FORECAST_TIMESTAMP, from 2018-01 (fills the NDF gap).
  Elexon Insights  /datasets/SYSWARN  NESO's system warnings (Electricity Margin Notice, Capacity
    Market Notice, High Risk of Demand Reduction, ...) with their free text, by publish time.

Output: data/raw/forecasts/{dataset}_{year}.csv ; LOLPDRM_horizons_{year}.csv ; SYSWARN_{year}.csv ;
        neso_da_demand_cardinal_points.csv

Usage:
  python -m gbpowerdata.pull.forecast_pull elexon --datasets WINDFOR,DGWS --start 2016 --end 2025
  python -m gbpowerdata.pull.forecast_pull elexon --datasets NDF,MELNGC,INDGEN --start 2021 --end 2025
  python -m gbpowerdata.pull.forecast_pull elexon --datasets LOLPDRM --start 2018 --end 2025 --window 10,13
  python -m gbpowerdata.pull.forecast_pull lolp --start 2018 --end 2025
  python -m gbpowerdata.pull.forecast_pull syswarn --start 2018 --end 2026
  python -m gbpowerdata.pull.forecast_pull neso
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
OUT = cfg.raw_dir() / "forecasts"
NESO_CKAN = "https://api.neso.energy/api/3/action"
NESO_DA_DEMAND_HIST = "9847e7bb-986e-49be-8138-717b25933fbb"   # Historic Day Ahead Demand Forecasts
NESO_EMBEDDED_ARCHIVE = {                                        # Embedded Solar and Wind Forecast Archive <year>
    2019: "bc4d1093-ecf2-46d8-b207-7a0e3e8fb957", 2020: "8a7249d4-ee67-45aa-9641-a3e063f54dba",
    2021: "794107f5-8567-4b32-ae3a-6817fec73e5c", 2022: "07b0b42c-5152-4fc5-bcd1-e10ec8ec07de",
    2023: "26c9ef64-ce43-4e22-b984-ef013636aacb", 2024: "06abd00a-ef6b-488b-9b6d-5e08fdc0c890",
    2025: "fc13df13-2dad-4a1c-b9e3-4569efba4955",
}
NATIONAL_ONLY = {"NDF", "MELNGC", "INDGEN"}                     # keep boundary == "N" only


def _get(url: str, params: dict, tries: int = 6, timeout: int = 90) -> dict:
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** k)
    raise RuntimeError(f"failed after {tries} tries: {url} {params}")


def _day_rows(dataset: str, d1: date, w_from: int, w_to: int) -> list[dict]:
    p = {"publishDateTimeFrom": f"{d1:%Y-%m-%d}T{w_from:02d}:00Z",
         "publishDateTimeTo": f"{d1:%Y-%m-%d}T{w_to:02d}:00Z"}
    rows = _get(f"{BASE_URL}/datasets/{dataset}", p).get("data", [])
    if dataset in NATIONAL_ONLY:
        rows = [r for r in rows if r.get("boundary") == "N"]
    return rows


def pull_elexon(datasets: list[str], start: int, end: int, w_from: int = 6, w_to: int = 9,
                sleep_s: float = 0.15) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).date()
    for ds in datasets:
        for year in range(start, end + 1):
            out = OUT / f"{ds}_{year}.csv"
            if out.exists() and year < today.year:              # the current year is never complete
                print(f"[{ds} {year}] exists, skip", flush=True)
                continue
            rows: list[dict] = []
            d1 = date(year, 1, 1) - timedelta(days=1)           # publications on D-1 for D in year
            last = min(date(year, 12, 31) - timedelta(days=1), today)
            n_days = 0
            t0 = time.time()
            while d1 <= last:
                try:
                    rows.extend(_day_rows(ds, d1, w_from, w_to))
                except RuntimeError as e:
                    print(f"  ! {ds} {d1}: {e}", flush=True)
                n_days += 1
                if n_days % 60 == 0:
                    print(f"  [{ds} {year}] {n_days} days, {len(rows)} rows, {time.time() - t0:.0f}s", flush=True)
                d1 += timedelta(days=1)
                time.sleep(sleep_s)
            df = pd.DataFrame(rows)
            tmp = out.with_suffix(".part.csv")
            df.to_csv(tmp, index=False)
            tmp.replace(out)
            print(f"[{ds} {year}] {len(df)} rows -> {out.name} ({time.time() - t0:.0f}s)", flush=True)


def pull_lolp_horizons(start: int, end: int, sleep_s: float = 0.2) -> None:
    """LOLPDRM at the fixed horizons (12, 8, 4, 2, 1 h before each settlement period), by delivery
    time in 6-day requests (the endpoint refuses ranges over 7 days, ends inclusive)."""
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    for year in range(start, end + 1):
        out = OUT / f"LOLPDRM_horizons_{year}.csv"
        if out.exists() and year < now.year:                   # the current year is never complete
            print(f"[LOLPDRM horizons {year}] exists, skip", flush=True)
            continue
        rows: list[dict] = []
        t = datetime(year, 1, 1, tzinfo=timezone.utc)          # UK time is UTC in January
        stop = min(datetime(year + 1, 1, 1, tzinfo=timezone.utc), now)
        t0 = time.time()
        while t < stop:
            t1 = min(t + timedelta(days=6), stop)
            try:
                rows.extend(_get(f"{BASE_URL}/forecast/system/loss-of-load",
                                 {"from": f"{t:%Y-%m-%dT%H:%MZ}", "to": f"{t1:%Y-%m-%dT%H:%MZ}"}).get("data", []))
            except RuntimeError as e:
                print(f"  ! LOLPDRM horizons {t:%Y-%m-%d}: {e}", flush=True)
            t = t1
            time.sleep(sleep_s)
        df = pd.DataFrame(rows).drop_duplicates(subset=["startTime", "forecastHorizon", "publishTime"])
        tmp = out.with_suffix(".part.csv")
        df.to_csv(tmp, index=False)
        tmp.replace(out)
        print(f"[LOLPDRM horizons {year}] {len(df)} rows -> {out.name} ({time.time() - t0:.0f}s)", flush=True)


def pull_syswarn(start: int, end: int, sleep_s: float = 0.2) -> None:
    """NESO's system warnings as published on BMRS (dataset SYS_WARN): Electricity Margin Notices,
    Capacity Market Notices, High Risk of Demand Reduction, demand control and the rest, with their
    free text (the affected periods and the margin shortfall are in the text, not in fields). By
    publish time in monthly requests; one CSV per year of publication. The Insights archive holds
    warnings from 2023 only (checked 30 September 2026: 2018-2022 return nothing)."""
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    for year in range(start, end + 1):
        out = OUT / f"SYSWARN_{year}.csv"
        if out.exists() and year < now.year:
            print(f"[SYSWARN {year}] exists, skip", flush=True)
            continue
        rows: list[dict] = []
        for m in range(1, 13):
            t0 = datetime(year, m, 1, tzinfo=timezone.utc)
            if t0 > now:
                break
            t1 = datetime(year + (m == 12), m % 12 + 1, 1, tzinfo=timezone.utc)
            try:
                rows.extend(_get(f"{BASE_URL}/datasets/SYSWARN", {"publishDateTimeFrom": f"{t0:%Y-%m-%dT%H:%MZ}",
                                                                   "publishDateTimeTo": f"{t1:%Y-%m-%dT%H:%MZ}"}).get("data", []))
            except RuntimeError as e:
                print(f"  ! SYSWARN {t0:%Y-%m}: {e}", flush=True)
            time.sleep(sleep_s)
        df = pd.DataFrame(rows)
        if df.empty:                      # the Insights archive starts in 2023; write nothing to cache
            print(f"[SYSWARN {year}] none published on BMRS Insights", flush=True)
            continue
        df = df.drop_duplicates(subset=["publishTime", "warningType", "warningText"]).sort_values("publishTime")
        df.to_csv(out, index=False)
        print(f"[SYSWARN {year}] {len(df)} warnings -> {out.name}", flush=True)


def pull_neso_da_demand() -> None:
    """Cardinal-point historic day-ahead demand forecasts (2018-), paginated CKAN datastore."""
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "neso_da_demand_cardinal_points.csv"
    rows, offset, page = [], 0, 32_000
    while True:
        res = _get(f"{NESO_CKAN}/datastore_search",
                   {"resource_id": NESO_DA_DEMAND_HIST, "limit": page, "offset": offset})["result"]
        recs = res.get("records", [])
        rows.extend(recs)
        offset += len(recs)
        print(f"  neso cardinal points: {offset}/{res.get('total')}", flush=True)
        if not recs or offset >= int(res.get("total", 0)):
            break
    pd.DataFrame(rows).drop(columns=["_id"], errors="ignore").to_csv(out, index=False)
    print(f"-> {out} ({len(rows)} rows)", flush=True)


def pull_neso_embedded(start: int = 2019, end: int = 2025, w_from: str = "07:00", w_to: str = "09:00") -> None:
    """D-1 vintages (Forecast_Datetime in [w_from, w_to] on D-1) of NESO's hourly-updated embedded wind+solar
    forecast archive, for targets on D. Server-side SQL so we fetch ~50k rows/yr, not ~5M."""
    OUT.mkdir(parents=True, exist_ok=True)
    for year in range(start, end + 1):
        rid = NESO_EMBEDDED_ARCHIVE.get(year)
        out = OUT / f"neso_embedded_da_{year}.csv"
        if rid is None or out.exists():
            print(f"[embedded {year}] {'no resource' if rid is None else 'exists, skip'}", flush=True)
            continue
        rows, offset, page = [], 0, 20000
        while True:
            sql = (f'SELECT "SETTLEMENT_DATE","SETTLEMENT_PERIOD","DATE_GMT","TIME_GMT","EMBEDDED_WIND_FORECAST",'
                   f'"EMBEDDED_WIND_CAPACITY","EMBEDDED_SOLAR_FORECAST","EMBEDDED_SOLAR_CAPACITY","Forecast_Datetime" '
                   f'FROM "{rid}" WHERE "Forecast_Datetime"::timestamp::time BETWEEN ' + repr(w_from) + " AND " + repr(w_to) + " "
                   f'AND "SETTLEMENT_DATE"::timestamp::date = ("Forecast_Datetime"::timestamp::date + 1) '
                   f'ORDER BY "_id" LIMIT {page} OFFSET {offset}')
            try:
                recs = _get(f"{NESO_CKAN}/datastore_search_sql", {"sql": sql}, timeout=300)["result"]["records"]
            except RuntimeError as e:
                print(f"  ! embedded {year} offset {offset}: {e}", flush=True)
                break
            rows.extend(recs)
            offset += len(recs)
            print(f"  [embedded {year}] {offset} rows", flush=True)
            if len(recs) < page:
                break
        pd.DataFrame(rows).to_csv(out, index=False)
        print(f"[embedded {year}] {len(rows)} rows -> {out.name}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("source", choices=["elexon", "neso", "embedded", "lolp", "syswarn"])
    p.add_argument("--datasets", default="WINDFOR,DGWS")
    p.add_argument("--start", type=int, default=2016)
    p.add_argument("--end", type=int, default=2025)
    p.add_argument("--window", default="6,9", help="publish window on D-1, UTC hours from,to")
    a = p.parse_args(argv)
    if a.source == "elexon":
        w0, w1 = (int(x) for x in a.window.split(","))
        pull_elexon([d.strip().upper() for d in a.datasets.split(",")], a.start, a.end, w0, w1)
    elif a.source == "embedded":
        pull_neso_embedded(a.start, a.end)
    elif a.source == "lolp":
        pull_lolp_horizons(a.start, a.end)
    elif a.source == "syswarn":
        pull_syswarn(a.start, a.end)
    else:
        pull_neso_da_demand()


if __name__ == "__main__":
    main(sys.argv[1:])
