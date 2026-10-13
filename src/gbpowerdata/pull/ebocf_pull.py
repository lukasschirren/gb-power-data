"""Pull Elexon's indicative Balancing Mechanism cashflows of the storage units (batteries and pumped storage)
-> data/raw/ebocf/ebocf_{YYYY-MM}.csv, and with --dataset volumes their accepted BM volumes
-> data/raw/bm_volumes/bm_volumes_{YYYY-MM}.csv.

Why: a battery's physical notification is its traded position, so its wholesale energy can be valued from it, but
the energy the system operator moves it by in the Balancing Mechanism is paid at the prices of its accepted offers
and bids (in 2025 a fifth of the batteries' revenue in gbpowerdata.build.storage_revenues). Elexon derives, for every BM
unit and settlement period, the cashflow of its accepted bids and offers (dataset EBOCF, "indicative period BM unit
cashflows": the accepted volume of each bid-offer pair times its price, from the latest settlement calculation), so
the BM part of a unit's revenue needs no reconstruction from the bid-offer data and the acceptances. The accepted
volumes themselves (dataset DISPTAV, "indicative period BM unit volumes") move the unit away from its notified
position: notified energy plus accepted volume is its position after the BM, which a check of its state of charge
needs (docs/AUDIT.md A9-8).

Sources: Elexon Insights /balancing/settlement/indicative/{cashflows|volumes}/all/{bid|offer}/{settlementDate}
?bmUnit=... (free, no key; history from 2016). Signs as Elexon publishes them. Cashflows: positive is paid to the
unit's lead party (an accepted offer, or a bid at a negative price), negative is paid by it (a bid at a positive
price, which a battery pays to charge more or discharge less). Volumes (MWh): positive for accepted offers (more
output or less demand), negative for accepted bids; Elexon gives each unit and period four data types, of which
"Original" is the whole accepted volume (the others are the variants the imbalance price is computed from: priced,
re-priced, tagged).

Units: every T_ and E_ unit that a kept snapshot of Elexon's register classes as battery or pumped storage
(gbpowerdata.build.bm_units.register), and the supplier (2__) and virtual lead party (V__) storage units of
data/processed/storage_fleet.csv (gbpowerdata.build.storage_fleet: the register gives these units no fuel type, and
NESO's results name their technology; left out without the table), BATCH per request. On 20 Nov 2025, 47 of the
fleet's 103 supplier and virtual lead party batteries had accepted bids or offers, GBP 78k in the day. A unit that
left the register before the first kept snapshot is not pulled (the limit of the register tables,
docs/ownership.md).

Output: one CSV per calendar month of settlement dates, only the rows with a non-zero total:
  settlementDate, settlementPeriod, startTime (UTC), bmUnit, nationalGridBmUnit, side (bid | offer),
  cashflow_gbp (volume_mwh for the volumes), createdDateTime
and beside it {name}_{YYYY-MM}.units, the units whose rows the file holds (one per line), since a unit without a
cashflow has no row. A month's rows are written only when every request for them succeeded (an empty month gets a
file with the header). A month on disk is pulled again only for the units it does not hold (one added to the
register or the fleet since), whose rows are merged in; a cashflow file written before the unit lists were kept (10
Oct 2026) holds the register's storage units of the snapshots kept on the day it was written. The current month is
pulled again for every unit on every run, to yesterday. Resumable.

Usage:
  python -m gbpowerdata.pull.ebocf_pull                              # cashflows, 2018-01 to the current month
  python -m gbpowerdata.pull.ebocf_pull --start 2024-01 --end 2024-12
  python -m gbpowerdata.pull.ebocf_pull --dataset volumes            # the accepted volumes (about 1 min a month)
Run gbpowerdata.build.storage_fleet before it (for the supplier and virtual lead party units) and again after it
(for their dates of first and last BM action).
"""
from __future__ import annotations

import argparse
import functools
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg


@dataclass(frozen=True)
class Dataset:
    """One of Elexon's indicative settlement datasets per BM unit and settlement period, pulled the same way."""
    endpoint: str                  # .../balancing/settlement/indicative/{endpoint}/all/{side}/{day}
    name: str                      # the folder and file names: data/raw/{name}/{name}_{YYYY-MM}.csv
    total: str                     # Elexon's total per unit, period and side
    column: str                    # its column here
    data_type: str | None = None   # the one data type kept where Elexon gives several per unit and period


CASHFLOWS = Dataset("cashflows", "ebocf", "totalCashflow", "cashflow_gbp")
VOLUMES = Dataset("volumes", "bm_volumes", "totalVolumeAccepted", "volume_mwh", "Original")
DATASETS = {"cashflows": CASHFLOWS, "volumes": VOLUMES}
URL = "https://data.elexon.co.uk/bmrs/api/v1/balancing/settlement/indicative/{endpoint}/all/{side}/{day}"
RAW = cfg.raw_dir()
SIDES = ("bid", "offer")
STORAGE = ("battery", "pumped_storage")
FLEET_KINDS = ("supplier", "vlp")      # storage_fleet's units outside T_ and E_ that have an Elexon id
BATCH = 60            # units per request (the unit list goes in the query string)
WORKERS = 4
KEY = ["settlementDate", "settlementPeriod", "bmUnit", "side"]


def columns(ds: Dataset = CASHFLOWS) -> list[str]:
    return ["settlementDate", "settlementPeriod", "startTime", "bmUnit", "nationalGridBmUnit", "side", ds.column,
            "createdDateTime"]


COLUMNS = columns(CASHFLOWS)


def month_path(year: int, month: int, ds: Dataset = CASHFLOWS) -> Path:
    return RAW / ds.name / f"{ds.name}_{year}-{month:02d}.csv"


@functools.lru_cache(maxsize=None)
def register_storage_units(before: date | None = None) -> tuple[str, ...]:
    """Every T_/E_ unit a kept register snapshot (dated on or before `before`; all by default) classes as battery or
    pumped storage; the oldest snapshot's where none is that old."""
    from gbpowerdata.build import bm_units as B

    files = B.register_files()
    if before is not None:
        kept = {k: v for k, v in files.items() if k.date() <= before}
        files = kept or dict([next(iter(files.items()))])
    units: set[str] = set()
    for path in files.values():
        reg = B.register(path)
        units |= set(reg.loc[reg["tech"].isin(STORAGE), "unit_id"].astype(str))
    return tuple(sorted(units))


def fleet_units() -> list[str]:
    """The supplier (2__) and virtual lead party (V__) storage units of storage_fleet; none without the table."""
    from gbpowerdata import processed as P

    try:
        f = P.read_storage_fleet()
    except FileNotFoundError:
        return []
    return sorted(f.loc[f["kind"].isin(FLEET_KINDS), "unit_id"].dropna().astype(str).unique())


def storage_units() -> list[str]:
    """The register's storage units and the fleet's supplier and virtual lead party storage units."""
    return sorted(set(register_storage_units()) | set(fleet_units()))


def units_path(path: Path) -> Path:
    return path.with_suffix(".units")


def held_units(path: Path, ds: Dataset = CASHFLOWS) -> set[str]:
    """The units whose rows a month file holds: its unit list; for a cashflow file written before the lists were
    kept, the register's storage units of the snapshots kept on the day it was written; else none."""
    listed = units_path(path)
    if listed.exists():
        return set(listed.read_text(encoding="utf-8").split())
    if ds is not CASHFLOWS:
        return set()
    written = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).date()
    return set(register_storage_units(before=written))


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


def rows(payload: dict, side: str, ds: Dataset = CASHFLOWS) -> list[dict]:
    """The non-zero totals of one response (of the dataset's data type where it has several), in columns(ds)."""
    out = []
    for d in payload.get("data", []):
        if ds.data_type is not None and d.get("dataType") != ds.data_type:
            continue
        v = d.get(ds.total)
        if v is None or float(v) == 0.0:
            continue
        out.append({"settlementDate": d.get("settlementDate"), "settlementPeriod": d.get("settlementPeriod"),
                    "startTime": d.get("startTime"), "bmUnit": d.get("bmUnit"),
                    "nationalGridBmUnit": d.get("nationalGridBmUnit"), "side": side,
                    ds.column: float(v), "createdDateTime": d.get("createdDateTime")})
    return out


def fetch(day: date, side: str, units: list[str], ds: Dataset = CASHFLOWS) -> list[dict]:
    url = URL.format(endpoint=ds.endpoint, side=side, day=f"{day:%Y-%m-%d}")
    return rows(_get(url, {"bmUnit": units, "format": "json"}), side, ds)


def month_days(year: int, month: int, last: date) -> list[date]:
    """The settlement dates of a month up to `last`."""
    first = date(year, month, 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return [first + timedelta(days=i) for i in range((min(nxt - timedelta(days=1), last) - first).days + 1)]


def pull_month(year: int, month: int, units: list[str], last: date, workers: int = WORKERS,
               ds: Dataset = CASHFLOWS) -> pd.DataFrame | None:
    """The month's non-zero totals of `units`; None if any request failed."""
    days = month_days(year, month, last)
    batches = [units[i:i + BATCH] for i in range(0, len(units), BATCH)]
    tasks = [(d, s, b) for d in days for s in SIDES for b in batches]
    out: list[dict] = []
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, d, s, b, ds): (d, s, b) for d, s, b in tasks}
        for fut, task in futures.items():
            try:
                out.extend(fut.result())
            except RuntimeError:
                failed.append(task)
    for d, s, b in list(failed):                          # one more try, one at a time
        try:
            out.extend(fetch(d, s, b, ds))
            failed.remove((d, s, b))
        except RuntimeError:
            pass
    if failed:
        print(f"  {year}-{month:02d}: {len(failed)} requests failed, not written "
              f"(e.g. {failed[0][0]} {failed[0][1]})", flush=True)
        return None
    return pd.DataFrame(out, columns=columns(ds))


def write_month(path: Path, rows: pd.DataFrame, units: set[str], ds: Dataset = CASHFLOWS) -> None:
    """Write a month's rows, then the list of units they cover (each whole or not at all: a file left without its
    new list is pulled again for those units and merged by KEY)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = rows.drop_duplicates(KEY, keep="last").sort_values(KEY)
    rows[columns(ds)].to_csv(path.with_suffix(".part"), index=False)
    path.with_suffix(".part").replace(path)
    listed = units_path(path)
    listed.with_suffix(".units_part").write_text("\n".join(sorted(units)) + "\n", encoding="utf-8")
    listed.with_suffix(".units_part").replace(listed)


def update_month(year: int, month: int, units: list[str], last: date, current: bool,
                 workers: int = WORKERS, ds: Dataset = CASHFLOWS) -> int | None:
    """Pull the units a month's file does not hold (every unit for the current month) and merge them in. Returns the
    number of units pulled (0: nothing to do), or None if a request failed."""
    path = month_path(year, month, ds)
    held = held_units(path, ds) if path.exists() and not current else set()
    todo = [u for u in units if u not in held]
    if not todo:
        return 0
    new = pull_month(year, month, todo, last, workers, ds)
    if new is None:
        return None
    old = pd.read_csv(path) if held else pd.DataFrame(columns=columns(ds))
    parts = [x for x in (old, new) if len(x)]
    write_month(path, pd.concat(parts, ignore_index=True) if parts else new, held | set(todo), ds)
    return len(todo)


def months(start: str, end: str) -> list[tuple[int, int]]:
    p = pd.period_range(pd.Period(start, "M"), pd.Period(end, "M"), freq="M")
    return [(x.year, x.month) for x in p]


def main(argv: list[str] | None = None) -> int:
    today = datetime.now(timezone.utc).date()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", choices=sorted(DATASETS), default="cashflows")
    ap.add_argument("--start", default="2018-01", help="first month, YYYY-MM")
    ap.add_argument("--end", default=f"{today:%Y-%m}", help="last month, YYYY-MM (default: the current month)")
    ap.add_argument("--workers", type=int, default=WORKERS)
    a = ap.parse_args(argv)
    ds = DATASETS[a.dataset]
    units = storage_units()
    fleet = fleet_units()
    last = today - timedelta(days=1)
    print(f"[{ds.name}] {len(units)} storage units ({len(fleet)} supplier and virtual lead party units of "
          f"storage_fleet), {a.start} to {a.end}", flush=True)
    for y, m in months(a.start, a.end):
        if date(y, m, 1) > last:
            break
        path = month_path(y, m, ds)
        t0 = time.time()
        n = update_month(y, m, units, last, current=(y, m) == (last.year, last.month), workers=a.workers, ds=ds)
        if n == 0:
            print(f"  skip {path.name} (holds every unit)", flush=True)
        elif n is not None:
            count = sum(1 for _ in open(path, encoding="utf-8")) - 1
            print(f"  {path.name}: {n} units pulled, {count} non-zero rows in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
