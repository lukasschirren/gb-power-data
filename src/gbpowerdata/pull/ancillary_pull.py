"""Pull NESO's unit-level results of its frequency response and reserve services -> data/raw/neso/ancillary/.

Why: a battery earns in three places, the wholesale market, the Balancing Mechanism and the services the system
operator buys to hold frequency and reserve, which paid most of a GB battery's revenue in 2021 and 2022. NESO
publishes, for every unit and delivery period, the MW each service bought, the price it paid and the company that
bid the unit into the auction (often the optimiser that trades a battery, not its owner).
gbpowerdata.build.ancillary_services puts the results of the different services and years into one table, and
gbpowerdata.build.storage_revenues adds them to the storage units' energy margins.

Sources: NESO Data Portal (CKAN at api.neso.energy, no key, NESO Open Data Licence), one file per resource:
  dataset dynamic-containment-data
    "Dynamic Containment Masterdata"                       dc_tender_2020_2021         DC low-frequency tenders,
                                                                                       2 Oct 2020 to 15 Sep 2021
    "DC, DR & DM Results By Unit Master Data 2021-2023"    dc_dr_dm_by_unit_2021_2023  the day-ahead auctions run
                                                                                       on EPEX, 16 Sep 2021 to 2 Nov 2023
  dataset eac-auction-results (NESO's Enduring Auction Capability, from 2 Nov 2023; Quick Reserve from 2024,
  Balancing Reserve in it from late 2025, Slow Reserve from 2026)
    "NESO Response-Reserve Results By Unit FY{yyyy} (Archive)"  eac_by_unit_fy{yyyy}   one financial year each
    "NESO Response-Reserve Results By Unit"                eac_by_unit_current_{date}  the running financial year
    "NESO Response-Reserve Daily Results By Unit"          eac_by_unit_daily_{date}    the latest auction day
  dataset eac-br-auction-results
    "NESO Balancing-Reserve Results By Unit 2023-2024"     br_by_unit_2023_2024        12 Mar 2024 to 29 Oct 2025
  dataset static-firm-frequency-response-auction-results
    "Static Firm Frequency Response Auction Results"       sffr_results_{date}         1 Apr 2023 on (running)
  dataset firm-frequency-response-post-tender-reports (the monthly Firm Frequency Response tenders, closed)
    "Post Tender Report - TR108 Dec-18" ... "TR166 October 2023"   ffr_post_tender_tr{nnn}[_amended].{xlsx,xlsm,csv}
                                                           every tender of rounds TR108 (Dec 2018, for January 2019)
                                                           to TR166 (Oct 2023, for November 2023), accepted or not:
                                                           unit, technology, service frames by day type, fees (GBP/h)
  dataset phase-2-ffr-auction-results-summary (the weekly FFR auction trial, closed)
    "Phase 2 FFR Auction ResultsByUnit Masterdata 2019-2020" ...  ffr_auction_by_unit_{yyyy}_{yyyy}   static (LFS) and
                                                           dynamic (DLH) FFR per EFA block, 7 Dec 2019 to 30 Nov 2021
                                                           (the last auction's own file repeats the masterdata)
  dataset short-term-operating-reserve-stor-day-ahead-auction-results
    "STOR DA Auction Results"                              stor_da_results_{date}      every tender of the daily STOR
                                                           auctions from 1 Apr 2021: unit, BM or not, fuel, contracted
                                                           MW, clearing price, per service day (running)
  dataset stor-windows
    "STOR Windows"                                         stor_windows_{date}         the committed windows of each
                                                           service day, two a day in UK local time (running)
A resource NESO no longer updates (an archive, a closed service) is written once under its own name and skipped
afterwards. One it still updates is written under the date of the pull ({date} = YYYYMMDD) and pulled again on a
later day; the build reads the newest. The resources are matched by name (RULES), so a new archive (FY2026, ...)
is pulled without a code change, and a renamed one is reported as unmatched by --list. A tender report is taken as
NESO published it (the file itself, "file" in RULES: most are workbooks outside the datastore, and the dump of the
CSV ones would add a column), under its round, "_amended" where NESO republished it.

Also pulled: gov.uk's bank holidays (https://www.gov.uk/bank-holidays.json, OGL; England and Wales from 2019) ->
data/raw/govuk/bank_holidays.json, refreshed when older than BANK_HOLIDAYS_MAX_AGE: a tender's frames differ on
Sundays and bank holidays.

Not here: the Enhanced Frequency Response contracts (2016 tender; published as a tender report, not as a unit-level
table), FFR tenders before TR108 (not on the portal, so a long-term contract accepted before December 2018 is
missing), STOR before April 2021 (seasonal tenders) and the non-BM units' long-term STOR contracts that run beside
the daily auctions (no unit-level table). Before January 2019 the storage revenue table therefore has no ancillary
income.

Output: data/raw/neso/ancillary/{stem}.csv, the CKAN datastore dump of the resource (NESO's columns and its _id), or
the published file for a "file" rule.

Usage:
  python -m gbpowerdata.pull.ancillary_pull           # every resource of RULES (archives already on disk skipped)
  python -m gbpowerdata.pull.ancillary_pull --list    # what the portal holds and what each resource maps to
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from gbpowerdata import config as cfg

CKAN = "https://api.neso.energy/api/3/action"
DUMP = "https://api.neso.energy/datastore/dump/{rid}"
OUT = cfg.raw_dir() / "neso" / "ancillary"
BANK_HOLIDAYS_URL = "https://www.gov.uk/bank-holidays.json"
BANK_HOLIDAYS = cfg.raw_dir() / "govuk" / "bank_holidays.json"
BANK_HOLIDAYS_MAX_AGE = timedelta(days=30)
# dataset slug -> [(pattern on the lower-case resource name, output stem with {groups}, updated by NESO?, how: "dump"
# for the datastore dump, "file" for the file as published)]
RULES = {
    "dynamic-containment-data": [
        (r"dynamic containment masterdata", "dc_tender_2020_2021", False, "dump"),
        (r"dc, dr & dm results by unit master data (\d{4})-(\d{4})", "dc_dr_dm_by_unit_{0}_{1}", False, "dump"),
    ],
    "eac-auction-results": [
        (r"neso response-reserve results by unit fy(\d{4}) \(archive\)", "eac_by_unit_fy{0}", False, "dump"),
        (r"neso response-reserve results by unit", "eac_by_unit_current", True, "dump"),
        (r"neso response-reserve daily results by unit", "eac_by_unit_daily", True, "dump"),
    ],
    "eac-br-auction-results": [
        (r"neso balancing-reserve results by unit (\d{4})-(\d{4})", "br_by_unit_{0}_{1}", False, "dump"),
        (r"neso balancing-reserve results by unit", "br_by_unit_current", True, "dump"),
    ],
    "static-firm-frequency-response-auction-results": [
        (r"static firm frequency response auction results", "sffr_results", True, "dump"),
    ],
    "firm-frequency-response-post-tender-reports": [
        (r"post tender report\W*tr\s?(\d{3})\b.*", "ffr_post_tender_tr{0}", False, "file"),
    ],
    "phase-2-ffr-auction-results-summary": [
        (r"phase 2 ffr auction resultsbyunit masterdata\W*(\d{4})-(\d{4})", "ffr_auction_by_unit_{0}_{1}", False, "dump"),
    ],
    "short-term-operating-reserve-stor-day-ahead-auction-results": [
        (r"stor da auction results", "stor_da_results", True, "dump"),
    ],
    "stor-windows": [
        (r"stor windows", "stor_windows", True, "dump"),
    ],
}
FILE_TYPES = (".csv", ".xlsx", ".xlsm")


def _get(url: str, params: dict | None = None, tries: int = 6, timeout: int = 120) -> requests.Response:
    for k in range(tries):
        try:
            r = requests.get(url, params=params, timeout=timeout, stream=True)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** k)
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 ** k)
    raise RuntimeError(f"failed after {tries} tries: {url} {params}")


def stem_for(dataset: str, name: str) -> tuple[str, bool, str] | None:
    """(output stem, updated by NESO, how) for a resource of `dataset` called `name`; None if no rule matches. A rule
    must match the whole name, so "... results by unit" does not catch "... results by unit fy2024 (archive)"."""
    low = re.sub(r"\s+", " ", str(name)).strip().lower()
    for pattern, stem, live, how in RULES.get(dataset, []):
        m = re.fullmatch(pattern, low)
        if m:
            return stem.format(*m.groups()), live, how
    return None


def file_name(stem: str, name: str, url: str) -> str | None:
    """The file name of a "file" resource: its stem, "_amended" where NESO republished it, and the published file's
    extension; None for a type the build does not read."""
    ext = Path(str(url).split("?")[0]).suffix.lower()
    if ext not in FILE_TYPES:
        return None
    amended = "amended" in f"{name} {url}".lower()
    return f"{stem}{'_amended' if amended else ''}{ext}"


def resources() -> list[dict]:
    """Every resource of the RULES datasets the build reads (the datastore ones, and the files of "file" rules), with
    its stem (None where no rule matches)."""
    out = []
    for dataset in RULES:
        pkg = _get(f"{CKAN}/package_show", {"id": dataset}).json()["result"]
        for res in pkg["resources"]:
            hit = stem_for(dataset, res.get("name", ""))
            how = hit[2] if hit else "dump"
            if how == "dump" and not res.get("datastore_active"):
                continue
            stem = hit[0] if hit else None
            if stem and how == "file":
                stem = file_name(stem, res.get("name", ""), res.get("url", ""))
            out.append({"dataset": dataset, "name": res.get("name", ""), "id": res["id"], "url": res.get("url"),
                        "stem": stem, "live": hit[1] if hit else None, "how": how})
    return out


def target(stem: str, live: bool, today: str, how: str = "dump") -> Path:
    if how == "file":
        return OUT / stem                                   # the stem carries the published file's extension
    return OUT / (f"{stem}_{today}.csv" if live else f"{stem}.csv")


def download(rid: str, path: Path, url: str | None = None) -> int:
    """Stream the datastore dump of resource `rid` (or the file at `url`) to `path`, written whole or not at all;
    returns bytes."""
    part = path.with_suffix(".part")
    r = _get(url or DUMP.format(rid=rid), timeout=600)
    n = 0
    with open(part, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            n += len(chunk)
    part.replace(path)
    return n


def pull_bank_holidays(path: Path = BANK_HOLIDAYS, max_age: timedelta = BANK_HOLIDAYS_MAX_AGE) -> bool:
    """gov.uk's bank holidays to `path` when it is missing or older than `max_age`; returns whether it was pulled."""
    if path.exists() and datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < max_age:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    download("", path, url=BANK_HOLIDAYS_URL)
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="list the portal's resources and their stems, pull nothing")
    a = ap.parse_args(argv)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    found = resources()
    if a.list:
        for r in found:
            print(f"  {r['dataset']:48s} {r['name'][:60]:60s} -> {r['stem'] or '(not pulled)'}")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for r in found:
        if r["stem"] is None:
            continue
        path = target(r["stem"], r["live"], today, r["how"])
        if path.exists():
            print(f"  skip {path.name} (exists)", flush=True)
            continue
        t0 = time.time()
        n = download(r["id"], path, url=r["url"] if r["how"] == "file" else None)
        print(f"  {path.name}: {n / 1e6:.1f} MB in {time.time() - t0:.0f} s", flush=True)
    if pull_bank_holidays():
        print(f"  {BANK_HOLIDAYS.name}: pulled", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
