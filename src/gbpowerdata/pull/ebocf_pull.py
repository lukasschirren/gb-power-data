"""Pull Elexon's indicative Balancing Mechanism cashflows of the storage units (batteries and pumped storage)
-> data/raw/ebocf/ebocf_{YYYY-MM}.csv.

Why: a battery's physical notification is its traded position, so its wholesale energy can be valued from it, but
the energy the system operator moves it by in the Balancing Mechanism is paid at the prices of its accepted offers
and bids (in 2025 a fifth of the batteries' revenue in gbpowerdata.build.storage_revenues). Elexon derives, for every BM
unit and settlement period, the cashflow of its accepted bids and offers (dataset EBOCF, "indicative period BM unit
cashflows": the accepted volume of each bid-offer pair times its price, from the latest settlement calculation), so
the BM part of a unit's revenue needs no reconstruction from the bid-offer data and the acceptances.

Source: Elexon Insights /balancing/settlement/indicative/cashflows/all/{bid|offer}/{settlementDate}?bmUnit=...
(free, no key; history from 2016). Sign as Elexon publishes it: positive is paid to the unit's lead party (an
accepted offer, or a bid at a negative price), negative is paid by it (a bid at a positive price, which a battery
pays to charge more or discharge less).

Units: every T_ and E_ unit that a kept snapshot of Elexon's register classes as battery or pumped storage
(gbpowerdata.build.bm_units.register), BATCH per request. A unit that left the register before the first kept
snapshot is not pulled (the limit of the register tables, docs/ownership.md).

Output: one CSV per calendar month of settlement dates, only the rows with a non-zero cashflow:
  settlementDate, settlementPeriod, startTime (UTC), bmUnit, nationalGridBmUnit, side (bid | offer),
  cashflow_gbp, createdDateTime
A month is written only when every request for it succeeded (an empty month gets a file with the header), so a
month with a file is complete; the current month is pulled again on every run, to yesterday. Resumable.

Usage:
  python -m gbpowerdata.pull.ebocf_pull                              # 2018-01 to the current month
  python -m gbpowerdata.pull.ebocf_pull --start 2024-01 --end 2024-12
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from gbpowerdata import config as cfg

URL = "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/indicative/cashflows/all/{side}/{day}"
OUT = cfg.raw_dir() / "ebocf"
SIDES = ("bid", "offer")
STORAGE = ("battery", "pumped_storage")
BATCH = 60            # units per request (the unit list goes in the query string)
WORKERS = 4
COLUMNS = ["settlementDate", "settlementPeriod", "startTime", "bmUnit", "nationalGridBmUnit", "side",
           "cashflow_gbp", "createdDateTime"]


def storage_units() -> list[str]:
    """Every T_/E_ unit any kept register snapshot classes as battery or pumped storage."""
    from gbpowerdata.build import bm_units as B

    units: set[str] = set()
    for path in B.register_files().values():
        reg = B.register(path)
        units |= set(reg.loc[reg["tech"].isin(STORAGE), "unit_id"].astype(str))
    return sorted(units)


def _get(url: str, params: dict, tries: int = 6, timeout: int = 120) -> dict:
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
    raise RuntimeError(f"failed after {tries} tries: {url}")


def rows(payload: dict, side: str) -> list[dict]:
    """The non-zero cashflows of one response, in COLUMNS."""
    out = []
    for d in payload.get("data", []):
        cf = d.get("totalCashflow")
        if cf is None or float(cf) == 0.0:
            continue
        out.append({"settlementDate": d.get("settlementDate"), "settlementPeriod": d.get("settlementPeriod"),
                    "startTime": d.get("startTime"), "bmUnit": d.get("bmUnit"),
                    "nationalGridBmUnit": d.get("nationalGridBmUnit"), "side": side,
                    "cashflow_gbp": float(cf), "createdDateTime": d.get("createdDateTime")})
    return out


def fetch(day: date, side: str, units: list[str]) -> list[dict]:
    payload = _get(URL.format(side=side, day=f"{day:%Y-%m-%d}"), {"bmUnit": units, "format": "json"})
    return rows(payload, side)


def month_days(year: int, month: int, last: date) -> list[date]:
    """The settlement dates of a month up to `last`."""
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return [first + timedelta(days=i) for i in range((min(nxt - timedelta(days=1), last) - first).days + 1)]


def pull_month(year: int, month: int, units: list[str], last: date, workers: int = WORKERS) -> bool:
    """Pull one month; write its file only if every request succeeded. Returns whether it was written."""
    days = month_days(year, month, last)
    batches = [units[i:i + BATCH] for i in range(0, len(units), BATCH)]
    tasks = [(d, s, b) for d in days for s in SIDES for b in batches]
    out: list[dict] = []
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, d, s, b): (d, s, b) for d, s, b in tasks}
        for fut, task in futures.items():
            try:
                out.extend(fut.result())
            except RuntimeError:
                failed.append(task)
    for d, s, b in list(failed):                          # one more try, one at a time
        try:
            out.extend(fetch(d, s, b))
            failed.remove((d, s, b))
        except RuntimeError:
            pass
    if failed:
        print(f"  {year}-{month:02d}: {len(failed)} requests failed, not written "
              f"(e.g. {failed[0][0]} {failed[0][1]})", flush=True)
        return False
    df = pd.DataFrame(out, columns=COLUMNS).sort_values(["settlementDate", "settlementPeriod", "bmUnit", "side"])
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"ebocf_{year}-{month:02d}.csv"
    df.to_csv(path.with_suffix(".part"), index=False)
    path.with_suffix(".part").replace(path)
    return True


def months(start: str, end: str) -> list[tuple[int, int]]:
    p = pd.period_range(pd.Period(start, "M"), pd.Period(end, "M"), freq="M")
    return [(x.year, x.month) for x in p]


def main(argv: list[str] | None = None) -> int:
    today = datetime.now(timezone.utc).date()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", default="2018-01", help="first month, YYYY-MM")
    ap.add_argument("--end", default=f"{today:%Y-%m}", help="last month, YYYY-MM (default: the current month)")
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    units = storage_units()
    last = today - timedelta(days=1)
    print(f"[ebocf] {len(units)} storage units, {a.start} to {a.end}", flush=True)
    for y, m in months(a.start, a.end):
        path = OUT / f"ebocf_{y}-{m:02d}.csv"
        current = (y, m) == (last.year, last.month) or date(y, m, 1) > last
        if date(y, m, 1) > last:
            break
        if path.exists() and not current:
            print(f"  skip {path.name} (exists)", flush=True)
            continue
        t0 = time.time()
        if pull_month(y, m, units, last, a.workers):
            n = sum(1 for _ in open(path, encoding="utf-8")) - 1
            print(f"  {path.name}: {n} non-zero cashflows in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
