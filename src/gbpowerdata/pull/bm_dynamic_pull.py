"""Pull snapshots of the Balancing Mechanism dynamic data every BM unit declares to NESO
-> data/raw/bm_dynamic/{kind}_{date}_sp{sp}.csv

WHAT IT IS
    Under the Grid Code (BC1.A.1.5, BC2.5.3) every BM unit submits, and keeps current, the operating
    limits NESO may dispatch it within. Elexon publishes them free, without a key, on the Insights
    Solution API. They are the only GB source of PER-UNIT operating parameters for thermal plant:
        SEL / SIL        stable export / import limit, MW: the minimum stable level the unit can export at
        RURE / RDRE      run-up / run-down rates when exporting, MW/min, up to three segments with elbows (MW)
        RURI / RDRI      the same when importing (pumped storage, batteries)
        NDZ              notice to deviate from zero, min: notice a unit at zero needs to start
        NTO / NTB        notice to deliver offers / bids, min (capped at 2 min for gensets by the Grid Code)
        MZT              minimum zero time, min: how long an exporting unit stays off before it may export again
        MNZT             minimum non-zero time, min: how long a unit must stay on once instructed on
        MDV / MDP        maximum delivery volume (MWh) over the maximum delivery period (min)
    plus, for the same instant, each unit's MEL (maximum export limit) and FPN (dataset PN), so a
    declared SEL can be read against what the unit could export and whether it was running.
    Definitions: NESO Grid Code BC1.A.1.5 (https://www.neso.energy/document/33851/download) and the NESO
    Data Validation, Consistency & Defaulting Rules (https://www.neso.energy/document/381641/download),
    which give the units and valid ranges (rates 0.2-999 MW/min, times 0-999 min).

WHAT IS PULLED
    One snapshot per (date, settlement period): the values in force for every unit at that period.
    Four calls per snapshot (all units at once, ~2-3 MB together):
        dynamic  /balancing/dynamic/all          SEL SIL MZT MNZT MDV MDP NTB NTO NDZ
        rates    /balancing/dynamic/rates/all    RURE RDRE RURI RDRI (rate1, elbow2, rate2, elbow3, rate3)
        mels     /balancing/physical/all?dataset=MELS
        pn       /balancing/physical/all?dataset=PN
    For each unit and dataset an /all call returns the last record submitted before the period starts,
    plus any change made during it; gbpowerdata.build.bm_dynamic keeps the one in force at the start.
    The archive begins on 12 Sep 2016; a unit that has not re-declared a dataset since then is absent
    from it, and closed units stay in it with their last values (the build filters on the register).
    Default snapshots: settlement period 24 (11:30 UTC in winter, 10:30 UTC in summer) on the 15th of
    January, April, July and October of 2018-2025, so the summary sees every season; DEFAULT_DATES.

    Source and terms: Elexon Insights Solution (https://data.elexon.co.uk/bmrs/api/v1), BMRS data under
    Elexon's BMRS data licence (datapack SOURCES["elexon"]).

DECLARATIONS (--submissions)
    A snapshot shows the values in force at one instant; a unit that declared a value between two snapshots and
    changed it again before the next is missed. /datasets/{dataset}/stream?from&to returns every submission of a
    dynamic dataset in a window (time, bmUnit, nationalGridBmUnit and the value: volumeMax in MWh for MDV,
    periodMax or periodMin in minutes for MDP, MZT and MNZT, notice for NDZ, NTO and NTB, level for SEL and SIL,
    rate1, elbow2, rate2, elbow3, rate3 for the run rates), for every unit including supplier (2__) and virtual lead
    party (V__) units. pull_submissions writes one file per dataset and month from SUBMISSIONS_FROM (the archive's
    first month) to the current one, which is pulled again until it is over: submissions_{dataset}_{YYYY-MM}.csv.
    By default MDV and MDP, which gbpowerdata.build.storage_fleet reads with the snapshots; the declared minimum
    zero and non-zero times, notice and stable export limit of thermal plant (MZT, MNZT, NDZ, SEL) and their run
    rates (RURE, RDRE) with --submissions MZT MNZT NDZ SEL RURE RDRE. On 2-3 Jun 2025 the stream held 45 MZT, 86
    MNZT, 87 NDZ, 194 SEL and 167 RURE submissions (T_STAY-2, Staythorpe: MNZT 360 min, NDZ 58 min).

Usage (from code):  pull(dates);   CLI:  python -m gbpowerdata.pull.bm_dynamic_pull [YYYY-MM-DD ...] [--sp 24]
                    pull_submissions(datasets);
                    CLI:  python -m gbpowerdata.pull.bm_dynamic_pull --submissions [DATASET ...]   (default MDV MDP)
Cached per file: an existing file is skipped (delete it to pull it again).
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg

BASE = "https://data.elexon.co.uk/bmrs/api/v1"
KINDS = {
    "dynamic": ("/balancing/dynamic/all", {}),
    "rates": ("/balancing/dynamic/rates/all", {}),
    "mels": ("/balancing/physical/all", {"dataset": "MELS"}),
    "pn": ("/balancing/physical/all", {"dataset": "PN"}),
}
SP = 24
YEARS = range(2018, 2026)
DEFAULT_DATES = [f"{y}-{m:02d}-15" for y in YEARS for m in (1, 4, 7, 10)]
OUT = cfg.raw_dir() / "bm_dynamic"


def path(kind: str, date: str, sp: int = SP) -> Path:
    return OUT / f"{kind}_{date}_sp{sp}.csv"


def _get(url: str, params: dict, tries: int = 5) -> list[dict]:
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return r.json()["data"]
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** k)
    raise RuntimeError(f"Elexon request failed: {url} {params}")


SUBMISSIONS = ("MDV", "MDP")
DYNAMIC_DATASETS = ("SEL", "SIL", "MZT", "MNZT", "NDZ", "NTO", "NTB", "MDV", "MDP", "RURE", "RDRE", "RURI", "RDRI")
SUBMISSIONS_FROM = "2016-09"


def submissions_path(dataset: str, month: str) -> Path:
    return OUT / f"submissions_{dataset}_{month}.csv"


def _get_list(url: str, params: dict, tries: int = 5) -> list[dict]:
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=180)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** k)
    raise RuntimeError(f"Elexon request failed: {url} {params}")


def pull_submissions(datasets=SUBMISSIONS, start: str = SUBMISSIONS_FROM, end: str | None = None,
                     sleep_s: float = 0.3) -> list[Path]:
    """Every submission of the dynamic `datasets`, one file per dataset and month (the current month again until it
    is over)."""
    OUT.mkdir(parents=True, exist_ok=True)
    now = pd.Timestamp.now(tz="UTC").tz_localize(None)
    months = pd.period_range(start, end or now.strftime("%Y-%m"), freq="M")
    paths = []
    for ds in datasets:
        for m in months:
            out = submissions_path(ds, str(m))
            paths.append(out)
            over = m.end_time < now
            if out.exists() and over:
                continue
            rows = _get_list(f"{BASE}/datasets/{ds}/stream",
                             {"from": f"{m.start_time:%Y-%m-%d}T00:00Z", "to": f"{(m + 1).start_time:%Y-%m-%d}T00:00Z"})
            tmp = out.with_suffix(".part.csv")
            pd.DataFrame(rows, columns=None if rows else ["dataset", "time", "bmUnit", "nationalGridBmUnit"]).to_csv(
                tmp, index=False)
            tmp.replace(out)
            if rows:
                print(f"  {ds} {m}: {len(rows)} submissions", flush=True)
            time.sleep(sleep_s)
    return paths


def pull(dates: list[str] | None = None, sp: int = SP, sleep_s: float = 0.5) -> list[Path]:
    """Cache the four snapshot kinds for each date at settlement period `sp`; returns the file paths."""
    OUT.mkdir(parents=True, exist_ok=True)
    paths = []
    for d in sorted(set(dates or DEFAULT_DATES)):
        for kind, (endpoint, extra) in KINDS.items():
            out = path(kind, d, sp)
            paths.append(out)
            if out.exists():
                continue
            rows = _get(BASE + endpoint, {"settlementDate": d, "settlementPeriod": sp, "format": "json", **extra})
            tmp = out.with_suffix(".part.csv")
            pd.DataFrame(rows).to_csv(tmp, index=False)
            tmp.replace(out)
            print(f"  {kind:7s} {d} sp{sp}: {len(rows)} records", flush=True)
            time.sleep(sleep_s)
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dates", nargs="*", help="YYYY-MM-DD (default: the 15th of Jan/Apr/Jul/Oct 2018-2025)")
    ap.add_argument("--sp", type=int, default=SP, help="settlement period (default 24)")
    ap.add_argument("--submissions", nargs="*", metavar="DATASET", choices=DYNAMIC_DATASETS,
                    help="every submission of these dynamic datasets, by month, instead (default MDV MDP)")
    a = ap.parse_args(argv)
    if a.submissions is not None:
        pull_submissions(tuple(a.submissions) or SUBMISSIONS)
    else:
        pull(a.dates or None, a.sp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
