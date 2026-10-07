"""Who controls a company, and from when: Companies House's persons with significant control (PSC) as a dated table,
data/processed/company_control.csv.

Why: the ownership tables (gbpowerdata.build.build_ownership) reduce every company a register names to a group,
and a project company that no rule places resolves to itself (basis "self"). Companies House's register of persons
with significant control names each company's parent, the date it became one and the date it ceased to be, so it
places such a company in a group on a given date and dates the changes of control. This stage writes that register
as one table, so a lookup reads one file instead of a folder of snapshots, and the table can be read and checked
on its own.

Input: the snapshots of gbpowerdata.pull.companies_house_pull (data/raw/companies_house/{YYYYMMDD}/{number}.json),
the newest of each company: the latest pull-date folder that holds it, so a later pull of a few numbers adds to an
earlier full pull instead of replacing it. --stamp reads the folders up to a pull date (YYYYMMDD, checked: a date
of any other form is refused rather than silently matching no folder) and writes its own file (Output), so the
table the lookups read is always the table of every pull.

The table is gbpowerdata.common.company_control.snapshot_table(): one row per company and PSC, ceased ones
included, with the columns company_number, company_name, controller_kind, controller_name, controller_number,
ownership_band, voting_band, held_as ("trust" for a holding filed as a trustee's, which never makes a
controller), notified_on, ceased_on and snapshot (the pull date of the row's snapshot, so a blank ceased_on is
dated: the controller still held on that day). That module documents each column and holds the
reading side (control_table, controller_at, group_by_control), so gbpowerdata.common.companies can ask it for a
company's group without importing a build stage; it reads data/processed/company_control.csv where it exists and
the snapshots otherwise, and warns when the snapshots on disk show the file is out of date (a snapshot written
after it, or a pull with PSC entries dated after the file's newest snapshot value).

Name check: a controller's number is kept only where the snapshot of that number, if one was pulled, gives the
controller's name as its name or a previous name (compared by gbpowerdata.common.companies.norm). Otherwise the
number is blanked, with a WARNING naming both companies, and the chain stops at that controller: a mistyped
registration number in a filing would chain the company to a stranger. The puller makes the same check when it
follows parents.

Personal data: the snapshots hold no individual's name, address or birth date (the puller's filter), and the table
names no individual either: controller_name and controller_number are filled only for a corporate or legal-person
entry with a name and none of a person's details or titles (company_control.looks_personal), whatever a snapshot
holds. The build log prints counts, and company names in warnings.

Output: data/processed/company_control.csv, the table of every pull, which the lookups read; with --stamp YYYYMMDD,
data/processed/company_control_{YYYYMMDD}.csv instead, the table as of that pull date, which no lookup reads
(company_control.control_table(stamp) reads the snapshots up to that date itself) and which leaves
company_control.csv as it was. Dates as YYYY-MM-DD, blank when none; snapshot as YYYYMMDD; numbers as eight
characters of text. Written whole and then renamed, since lookups read it.

Usage: python -m gbpowerdata.build.build_company_control                     # data/processed/company_control.csv
       python -m gbpowerdata.build.build_company_control --stamp 20261006    # .../company_control_20261006.csv
       (after python -m gbpowerdata.pull.companies_house_pull --follow 2)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

from gbpowerdata import config as cfg
from gbpowerdata.common import company_control as cc


def stamp_arg(text: str) -> str:
    """argparse type of --stamp: a pull date as YYYYMMDD (company_control.valid_stamp)."""
    try:
        return cc.valid_stamp(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def summary(t: pd.DataFrame, companies: int) -> str:
    """Counts for the build log: companies pulled, rows, and the companies under a majority corporate controller
    today."""
    today = pd.Timestamp.today().normalize()
    held = t.loc[cc.in_force(t, today), "company_number"].nunique()
    corporate = int(t["controller_kind"].isin(cc.CORPORATE).sum())
    return (f"{companies} companies pulled, {t['company_number'].nunique()} with PSC entries: {len(t)} rows "
            f"({corporate} corporate or legal persons); {held} under a majority corporate controller today")


def output_path(out_dir: Path | None = None, stamp: str | None = None) -> Path:
    """out_dir (default the processed folder) / company_control.csv, the table of every pull; with a pull date,
    company_control_{stamp}.csv, so a table up to an earlier pull never replaces the one the lookups read."""
    out_dir = cfg.processed_dir() if out_dir is None else Path(out_dir)
    return out_dir / (cc.OUTPUT if stamp is None else cc.OUTPUT_STAMPED.format(stamp=cc.valid_stamp(stamp)))


def write(out_dir: Path | None = None, stamp: str | None = None) -> Path:
    """Write the table of the snapshots (up to `stamp`) to output_path(out_dir, stamp) and forget the table read so
    far in this process."""
    path = output_path(out_dir, stamp)
    t = cc.snapshot_table(stamp)
    part = path.with_name(path.name + ".part")      # whole, then renamed: a lookup never reads half a table
    t.to_csv(part, index=False, date_format="%Y-%m-%d")
    os.replace(part, path)
    cc.clear_cache()
    print(f"  {summary(t, len(cc.snapshot_files(stamp)))} -> {path}", flush=True)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stamp", type=stamp_arg, metavar="YYYYMMDD",
                    help="read the snapshot folders up to this pull date and write company_control_YYYYMMDD.csv; "
                         "default all, to company_control.csv")
    a = ap.parse_args(argv)
    write(stamp=a.stamp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
