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
A resource NESO no longer updates (an archive, a closed service) is written once under its own name and skipped
afterwards. One it still updates is written under the date of the pull ({date} = YYYYMMDD) and pulled again on a
later day; the build reads the newest. The resources are matched by name (RULES), so a new archive (FY2026, ...)
is pulled without a code change, and a renamed one is reported as unmatched by --list.

Not here: the monthly Firm Frequency Response tenders and the Enhanced Frequency Response contracts that paid
batteries before October 2020 (published as tender reports, not as unit-level tables), and the Short-Term
Operating Reserve. Before October 2020 the storage revenue table therefore has no ancillary income.

Output: data/raw/neso/ancillary/{stem}.csv, the CKAN datastore dump of the resource (NESO's columns and its _id).

Usage:
  python -m gbpowerdata.pull.ancillary_pull           # every resource of RULES (archives already on disk skipped)
  python -m gbpowerdata.pull.ancillary_pull --list    # what the portal holds and what each resource maps to
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from gbpowerdata import config as cfg

CKAN = "https://api.neso.energy/api/3/action"
DUMP = "https://api.neso.energy/datastore/dump/{rid}"
OUT = cfg.raw_dir() / "neso" / "ancillary"
# dataset slug -> [(pattern on the lower-case resource name, output stem with {groups}, updated by NESO?)]
RULES = {
    "dynamic-containment-data": [
        (r"dynamic containment masterdata", "dc_tender_2020_2021", False),
        (r"dc, dr & dm results by unit master data (\d{4})-(\d{4})", "dc_dr_dm_by_unit_{0}_{1}", False),
    ],
    "eac-auction-results": [
        (r"neso response-reserve results by unit fy(\d{4}) \(archive\)", "eac_by_unit_fy{0}", False),
        (r"neso response-reserve results by unit", "eac_by_unit_current", True),
        (r"neso response-reserve daily results by unit", "eac_by_unit_daily", True),
    ],
    "eac-br-auction-results": [
        (r"neso balancing-reserve results by unit (\d{4})-(\d{4})", "br_by_unit_{0}_{1}", False),
        (r"neso balancing-reserve results by unit", "br_by_unit_current", True),
    ],
    "static-firm-frequency-response-auction-results": [
        (r"static firm frequency response auction results", "sffr_results", True),
    ],
}


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


def stem_for(dataset: str, name: str) -> tuple[str, bool] | None:
    """(output stem, updated by NESO) for a resource of `dataset` called `name`; None if no rule matches. A rule
    must match the whole name, so "... results by unit" does not catch "... results by unit fy2024 (archive)"."""
    low = re.sub(r"\s+", " ", str(name)).strip().lower()
    for pattern, stem, live in RULES.get(dataset, []):
        m = re.fullmatch(pattern, low)
        if m:
            return stem.format(*m.groups()), live
    return None


def resources() -> list[dict]:
    """Every datastore resource of the RULES datasets, with its stem (None where no rule matches)."""
    out = []
    for dataset in RULES:
        pkg = _get(f"{CKAN}/package_show", {"id": dataset}).json()["result"]
        for res in pkg["resources"]:
            if not res.get("datastore_active"):
                continue
            hit = stem_for(dataset, res.get("name", ""))
            out.append({"dataset": dataset, "name": res.get("name", ""), "id": res["id"],
                        "stem": hit[0] if hit else None, "live": hit[1] if hit else None})
    return out


def target(stem: str, live: bool, today: str) -> Path:
    return OUT / (f"{stem}_{today}.csv" if live else f"{stem}.csv")


def download(rid: str, path: Path) -> int:
    """Stream the datastore dump of resource `rid` to `path` (written whole or not at all); returns bytes."""
    part = path.with_suffix(".part")
    r = _get(DUMP.format(rid=rid), timeout=600)
    n = 0
    with open(part, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)
            n += len(chunk)
    part.replace(path)
    return n


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
        path = target(r["stem"], r["live"], today)
        if path.exists():
            print(f"  skip {path.name} (exists)", flush=True)
            continue
        t0 = time.time()
        n = download(r["id"], path)
        print(f"  {path.name}: {n / 1e6:.1f} MB in {time.time() - t0:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
