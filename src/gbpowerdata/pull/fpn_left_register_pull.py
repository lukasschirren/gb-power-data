"""Pull the physical notifications of the BM units that left Elexon's register before its first kept snapshot, from
Elexon's all-units stream, and list every unit the register lacks that notified output.

WHY
    gbpowerdata.build.bm_units builds each year's register from the kept snapshots of Elexon's register (the first of
    5 Jun 2026), so a unit that left the register before then counted in no year. Among them were Eggborough (1,960 MW
    of coal), Cottam (2,000 MW), Aberthaw B (1,559 MW) and Deeside's CCGT (498 MW, listed by its National Grid id
    alone), so the register's coal was 7.2 GW in 2018 and 6.7 GW in 2019,
    below even the 10.9 and 7.3 GW DESNZ counts installed at those years' ends (DUKES 5.12, which leaves out a station
    closed during the year). Elexon's per-unit queries return nothing for such a unit under either of its ids: the PN
    stream and /balancing/physical with bmUnit gave no row for Cottam, Aberthaw B or Eggborough in weeks they ran
    (checked 14 Oct 2026), while Ratcliffe's units, still registered, gave theirs. Elexon's all-units stream
    (/datasets/PN/stream without a unit) still carries their notifications, under the National Grid id with Elexon's
    id empty.

METHOD
    One request a day over the window (default: 1 Mar 2016, where the FPN files of gbpowerdata.pull.fpn_pull start, to
    1 Apr 2020, the day after the last closure in the table; whole months), each about 0.6 MB as Elexon sends it
    (Brotli), about half an hour for the default window. Of each day it keeps the rows of every unit that no kept
    register snapshot lists with an Elexon id, under either of its ids (a unit a snapshot lists by its National Grid
    id alone is in no register table, since bm_units needs Elexon's id: 87 such ids in the snapshot of 5 Jun 2026,
    Deeside's CCGT and several hydro stations and wind farms among them), a month to a file
    (data/raw/fpn_unregistered/{YYYY-MM}.csv.gz; a month on disk is not pulled again, so an interrupted pull
    resumes). From those months, without the network (--cut-only, after the table changes):
      the table's units  data/reference/bmu_left_register.csv (gbpowerdata.build.bm_units.left_register), by its
                         National Grid id: every row, in fpn_pull's columns, to data/raw/fpn/{unit}.csv, so that
                         bm_units dates these units by the rule it dates every unit by; a unit of the table without a
                         row in the window is recorded as an empty pull (data/raw/fpn_without_notifications.csv:
                         inactive in every year). data/raw/fpn_left_register.csv records which files came from here.
      the scan           for every unregistered unit: its days with output by bm_units' rule (a notified level of at
                         least MIN_LEVEL_MW in at least MIN_DAY_PERIODS distinct half-hours of the day), the first and
                         last of them, its highest level, the first and last day it notified at all, the Power Station
                         Dictionary's Elexon id and station where it has the unit (data/reference/bmu_crosswalk.csv),
                         whether the table holds it and whether a snapshot lists it by its National Grid id alone
                         -> data/processed/bmu_unregistered_scan.csv. It is the
                         check that the table misses no unit: an unregistered unit with output and an Elexon T_ or E_
                         id belongs in the table, while supplier units (2__) are not in the register tables by design.
    The years after the window (--sample): one hour of the stream (17:00 to 18:00 UTC) every seventh day from 1 Apr
    2020 to the end of 2025, listing the unregistered units with output in it (data/processed/
    bmu_unregistered_sample.csv). Checked 14 Oct 2026, it found four: three supplier units of the Power Station
    Dictionary (Sandbach CHP, Castleford and Thornhill, 2__ ids, about 50 MW each, to September 2020), and PETDG-1, a
    flat 48 MW at the evening hour in 75 of the 301 samples, July 2020 to October 2023, which no source names (no
    Elexon id, no metered output, not in the Dictionary) and the table therefore leaves out.

Outputs
    data/raw/fpn_unregistered/{YYYY-MM}.csv.gz      nationalGridBmUnit, bmUnit and fpn_pull's columns
    data/raw/fpn/{unit}.csv                         the table's units, fpn_pull's columns
    data/raw/fpn_left_register.csv                  unit_id, ngc_id, window_from, window_to, rows, pulled
    data/processed/bmu_unregistered_scan.csv        ngc_id, stream_unit_id, psd_unit_id, psd_station, in_table,
                                                    snapshot_ngc_only, first_row, last_row, first_output,
                                                    last_output, output_days, max_level_mw

Source and terms: Elexon Insights Solution (https://data.elexon.co.uk/bmrs/api/v1), free and without a key; BMRS data
under the BMRS licence, as gbpowerdata.pull.fpn_pull.

Usage
    python -m gbpowerdata.pull.fpn_left_register_pull                 # pull the window, then cut and scan
    python -m gbpowerdata.pull.fpn_left_register_pull --pull-only     # the months only
    python -m gbpowerdata.pull.fpn_left_register_pull --cut-only      # cut and scan the months on disk
    python -m gbpowerdata.pull.fpn_left_register_pull --start 2016-03-01 --end 2020-04-01
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from gbpowerdata import config as cfg
from gbpowerdata.pull import fpn_pull

START, END = "2016-03-01", "2020-04-01"
COLUMNS = ["nationalGridBmUnit", "bmUnit", *fpn_pull.KEEP]
MONTHS = "fpn_unregistered"                 # raw folder of the monthly files
RECORD = "fpn_left_register.csv"            # raw folder: the table's files cut from the months
SCAN = "bmu_unregistered_scan.csv"     # processed folder
SAMPLE = "bmu_unregistered_sample.csv"  # processed folder: the check of the years after the window
SAMPLE_START, SAMPLE_END = END, "2026-01-01"
TRIES = 4


def _snapshots() -> pd.DataFrame:
    from gbpowerdata.build.bm_units import register_files

    s = pd.concat([pd.read_csv(p, usecols=["elexonBmUnit", "nationalGridBmUnit"], dtype=str)
                   for p in register_files().values()], ignore_index=True)
    return s.apply(lambda c: c.fillna("").str.strip())


def known_ids() -> set[str]:
    """The ids, Elexon's and National Grid's, of every unit a kept snapshot lists with an Elexon id: the units the
    register tables can hold (bm_units keeps the T_ and E_ ones). A unit listed by its National Grid id alone is in no
    table (bm_units needs the Elexon id), so it counts as unregistered here."""
    s = _snapshots()
    s = s[s["elexonBmUnit"] != ""]
    return (set(s["elexonBmUnit"]) | set(s["nationalGridBmUnit"])) - {""}


def ngc_only_ids() -> set[str]:
    """The National Grid ids a kept snapshot lists without an Elexon id and none lists with one (87 in the snapshot of
    5 Jun 2026, Deeside's CCGT and several hydro stations and wind farms among them)."""
    s = _snapshots()
    return set(s.loc[s["elexonBmUnit"] == "", "nationalGridBmUnit"]) - known_ids() - {""}


def unregistered_rows(data: list[dict], known: set[str]) -> pd.DataFrame:
    """The rows of the all-units stream whose unit no kept snapshot holds by either id and that carry a National
    Grid id (COLUMNS)."""
    keep = [x for x in data if x.get("nationalGridBmUnit") and x["nationalGridBmUnit"] not in known
            and (x.get("bmUnit") or "") not in known]
    return pd.DataFrame(keep, columns=COLUMNS)


def get_window(t0: pd.Timestamp, t1: pd.Timestamp) -> list[dict]:
    """The all-units PN stream from t0 to t1 (UTC)."""
    params = {"from": f"{t0:%Y-%m-%dT%H:%M}Z", "to": f"{t1:%Y-%m-%dT%H:%M}Z"}
    for k in range(TRIES):
        try:
            r = requests.get(fpn_pull.STREAM, params=params, timeout=300)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if k == TRIES - 1:
                raise
            print(f"  {t0}: request failed ({e}); retrying", flush=True)
            time.sleep(2 ** k)
    return []


def get_day(day: pd.Timestamp) -> list[dict]:
    """One day of the all-units PN stream (UTC midnight to midnight)."""
    return get_window(day, day + pd.Timedelta(days=1))


def months(start: str = START, end: str = END) -> pd.PeriodIndex:
    """The whole months the window [start, end) touches."""
    return pd.period_range(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1), freq="M")


def window(start: str = START, end: str = END) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The window the months cover: the first month's first day to the day after the last month's last."""
    m = months(start, end)
    return m[0].start_time, m[-1].end_time.normalize() + pd.Timedelta(days=1)


def month_file(month: pd.Period) -> Path:
    return cfg.raw_dir() / MONTHS / f"{month}.csv.gz"


def pull(start: str = START, end: str = END) -> None:
    """Pull every month of the window not yet on disk into data/raw/fpn_unregistered/{YYYY-MM}.csv.gz."""
    known = known_ids()
    todo = [m for m in months(start, end) if not month_file(m).exists()]
    print(f"  {len(todo)} months to pull ({len(known):,} ids in the kept snapshots)", flush=True)
    for month in todo:
        t0, frames = time.time(), []
        for day in pd.date_range(month.start_time, month.end_time.normalize(), freq="D"):
            frames.append(unregistered_rows(get_day(day), known))
            time.sleep(fpn_pull.SLEEP)
        m = pd.concat(frames, ignore_index=True)
        path = month_file(month)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        m.to_csv(tmp, index=False, compression="gzip")
        tmp.replace(path)                       # a month is on disk whole or not at all
        print(f"  {month}: {len(m):,} rows of {m['nationalGridBmUnit'].nunique()} unregistered units "
              f"({time.time() - t0:.0f} s)", flush=True)


def scan_month(m: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """A month's (days with output: nationalGridBmUnit, day; spans: per unit its first and last day, highest level and
    the stream's Elexon id where it gives one), by bm_units' rule for a day with output."""
    from gbpowerdata.build import bm_units as B

    m = m.assign(day=pd.to_datetime(m["settlementDate"].astype(str).str[:10], errors="coerce"),
                 lv=m[["levelFrom", "levelTo"]].astype(float).max(axis=1))
    hh = m.loc[m["lv"] >= B.MIN_LEVEL_MW, ["nationalGridBmUnit", "day", "settlementPeriod"]].drop_duplicates()
    per_day = hh.groupby(["nationalGridBmUnit", "day"]).size()
    out = per_day[per_day >= B.MIN_DAY_PERIODS].reset_index()[["nationalGridBmUnit", "day"]]
    spans = m.groupby("nationalGridBmUnit").agg(first_row=("day", "min"), last_row=("day", "max"),
                                                max_level_mw=("lv", "max"),
                                                stream_unit_id=("bmUnit", lambda s: next(iter(s.dropna()), "")))
    return out, spans


def cut(start: str = START, end: str = END) -> pd.DataFrame:
    """From the months on disk: the table's units' files (data/raw/fpn/{unit}.csv, recorded in data/raw/
    fpn_left_register.csv; units without a row recorded as empty pulls) and the scan of every unregistered unit
    (data/processed/bmu_unregistered_scan.csv, returned)."""
    from gbpowerdata.build import bm_units as B

    missing = [str(m) for m in months(start, end) if not month_file(m).exists()]
    if missing:
        raise FileNotFoundError(f"months not pulled yet: {missing[:3]}{'...' if len(missing) > 3 else ''} "
                                "(python -m gbpowerdata.pull.fpn_left_register_pull --pull-only)")
    table = B.left_register()
    ngc = dict(zip(table["ngc_id"], table["unit_id"]))
    parts: dict[str, list[pd.DataFrame]] = {u: [] for u in table["unit_id"]}
    outs, spans = [], []
    for month in months(start, end):
        m = pd.read_csv(month_file(month), dtype={"nationalGridBmUnit": str, "bmUnit": str})
        o, s = scan_month(m)
        outs.append(o)
        spans.append(s)
        for g, rows in m[m["nationalGridBmUnit"].isin(ngc)].groupby("nationalGridBmUnit"):
            parts[ngc[g]].append(rows[fpn_pull.KEEP])

    lo, hi = window(start, end)
    record_path = cfg.raw_dir() / RECORD
    ours = set(pd.read_csv(record_path, dtype=str)["unit_id"]) if record_path.exists() else set()
    record, empty = [], []
    for unit, g in zip(table["unit_id"], table["ngc_id"]):
        out = cfg.raw_dir() / "fpn" / f"{unit}.csv"
        if out.exists() and unit not in ours:
            raise FileExistsError(f"{out} exists and did not come from this module: a registered unit's file is not "
                                  "overwritten (is the unit in a register snapshot after all?)")
        if not parts[unit]:
            empty.append(unit)
            continue
        df = (pd.concat(parts[unit], ignore_index=True)
                .drop_duplicates(["settlementDate", "settlementPeriod", "timeFrom"])
                .sort_values(["settlementDate", "settlementPeriod", "timeFrom"]))
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        record.append({"unit_id": unit, "ngc_id": g, "window_from": lo.date(), "window_to": hi.date(),
                       "rows": len(df), "pulled": pd.Timestamp.today().date()})
    if empty:
        B.record_empty_pulls(empty, (lo, hi))
    pd.DataFrame(record, columns=["unit_id", "ngc_id", "window_from", "window_to", "rows", "pulled"]).to_csv(
        record_path, index=False)

    o = pd.concat(outs, ignore_index=True)
    days = o.groupby("nationalGridBmUnit")["day"].agg(first_output="min", last_output="max", output_days="nunique")
    s = pd.concat(spans).groupby(level=0).agg(first_row=("first_row", "min"), last_row=("last_row", "max"),
                                              max_level_mw=("max_level_mw", "max"),
                                              stream_unit_id=("stream_unit_id", "max"))
    scan = s.join(days, how="left")
    scan["output_days"] = scan["output_days"].fillna(0).astype(int)
    xw = pd.read_csv(cfg.reference_dir() / "bmu_crosswalk.csv", dtype=str).dropna(subset=["ngc_bmu_id"])
    xw = xw.drop_duplicates("ngc_bmu_id").set_index("ngc_bmu_id")
    scan["psd_unit_id"] = scan.index.map(xw["elexon_bmu_id"])
    scan["psd_station"] = scan.index.map(xw["station_name"])
    scan["in_table"] = scan.index.isin(set(ngc))
    scan["snapshot_ngc_only"] = scan.index.isin(ngc_only_ids())
    scan.index.name = "ngc_id"
    scan = scan.reset_index()[["ngc_id", "stream_unit_id", "psd_unit_id", "psd_station", "in_table",
                               "snapshot_ngc_only", "first_row", "last_row", "first_output", "last_output",
                               "output_days", "max_level_mw"]]
    scan = scan.sort_values(["output_days", "max_level_mw"], ascending=False, ignore_index=True)
    path = cfg.processed_dir() / SCAN
    scan.to_csv(path, index=False)
    with_output = int((scan["output_days"] > 0).sum())
    print(f"  {len(record)} of the table's {len(table)} units cut to data/raw/fpn ({len(empty)} without a row: "
          f"{', '.join(empty) or 'none'}); {len(scan)} unregistered units scanned, {with_output} with output -> "
          f"{path.name}", flush=True)
    return scan


def sample(start: str = SAMPLE_START, end: str = SAMPLE_END, every: int = 7, hour: int = 17,
           get=get_window) -> pd.DataFrame:
    """The check of the years after the window: one hour of the all-units stream (from `hour` UTC) every `every` days
    of [start, end), and every unit no kept snapshot lists with an Elexon id that notified at least MIN_LEVEL_MW in
    it, with its first and last such day, the number of them and its highest level -> data/processed/SAMPLE
    (returned). A unit producing for weeks in a year shows; one that ran a few days between samples may not."""
    from gbpowerdata.build import bm_units as B

    known, rows = known_ids(), []
    for day in pd.date_range(pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(days=1), freq=f"{every}D"):
        t0 = day + pd.Timedelta(hours=hour)
        m = unregistered_rows(get(t0, t0 + pd.Timedelta(hours=1)), known)
        m = m.assign(day=day, lv=m[["levelFrom", "levelTo"]].astype(float).max(axis=1))
        rows.append(m.loc[m["lv"] >= B.MIN_LEVEL_MW, ["nationalGridBmUnit", "day", "lv"]])
        if get is get_window:
            time.sleep(fpn_pull.SLEEP)
    s = pd.concat(rows, ignore_index=True)
    out = s.groupby("nationalGridBmUnit").agg(first_sampled=("day", "min"), last_sampled=("day", "max"),
                                              samples=("day", "nunique"), max_level_mw=("lv", "max"))
    xw = pd.read_csv(cfg.reference_dir() / "bmu_crosswalk.csv", dtype=str).dropna(subset=["ngc_bmu_id"])
    xw = xw.drop_duplicates("ngc_bmu_id").set_index("ngc_bmu_id")
    out["psd_unit_id"] = out.index.map(xw["elexon_bmu_id"])
    out["psd_station"] = out.index.map(xw["station_name"])
    out["snapshot_ngc_only"] = out.index.isin(ngc_only_ids())
    out.index.name = "ngc_id"
    out = out.reset_index().sort_values(["samples", "max_level_mw"], ascending=False, ignore_index=True)
    path = cfg.processed_dir() / SAMPLE
    out.to_csv(path, index=False)
    print(f"  {len(out)} unregistered units with output in the samples of {start} to {end} -> {path.name}", flush=True)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--pull-only", action="store_true", help="pull the months, do not cut or scan")
    ap.add_argument("--cut-only", action="store_true", help="cut and scan the months on disk, without the network")
    ap.add_argument("--sample", action="store_true",
                    help=f"only the check of the later years: an hour a week, {SAMPLE_START} to {SAMPLE_END}")
    a = ap.parse_args(argv)
    if a.sample:
        sample()
        return 0
    if not a.cut_only:
        pull(a.start, a.end)
    if not a.pull_only:
        cut(a.start, a.end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
