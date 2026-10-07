"""Pull NESO's Capacity Market Register (the EMR Delivery Body's register of every Capacity Market unit) into
data/raw/neso/cm_register/.

Why: the ownership tables (gbpowerdata.build.build_ownership) need who OWNS the batteries and the firm capacity.
Elexon's BM register names the company that trades a unit (its lead party), often an optimiser for a battery, and
DESNZ's list of power stations (DUKES 5.11) has no batteries. The CM register names, for every capacity market
unit (CMU) in every auction, the applicant, the registered holder of the capacity agreement and the PARENT
COMPANY (filled for 95% of the storage CMUs awarded for delivery year 2026, checked 6 Oct 2026), with technology,
storage duration, de-rated capacity and the delivery years the agreement covers. Its components carry the BM unit
of most transmission-connected and BM-registered embedded units as their Component ID ("T_DRAXX-5",
"E_PILLB-1"), which links a CMU to the units Elexon's register lists.

Source: NESO data portal (CKAN, no key), dataset "capacity-market-register", resolved by name at run time (the
resource ids change when NESO republishes):
  "Capacity Market Unit (CMU)"   one row per CMU and auction: Auction Name, Delivery Year, CMU ID, Name of
                                 Applicant, Agent Name, CM Unit Name, Parent Company, Transmission or Distribution,
                                 CM Unit Type/Category, Primary Fuel Type, CMU Technology, Storage Facility,
                                 Connection or DSR Capacity, De Rated Capacity, Capacity Agreement Awarded,
                                 Registered Holder, Delivery Years for which Agreement Valid, terminations
  "Components"                   one row per component of a CMU: Component ID, Generating Technology Class (e.g.
                                 "Storage (Duration 2h)"), Primary Fuel of Component, capacities, Description of
                                 CMU Components, Location and Post Code, OS Grid Reference. Since 22 Jul 2026 NESO
                                 aggregates components under 30 kW per technology class and CMU.
Licence: NESO Open Data Licence (the portal's licence for this dataset, checked 6 Oct 2026).

Personal data: the CMU file also lists each applicant's secondary trading contact (telephone and e-mail). Those
columns (every column whose name contains "contact") are dropped before the file is written, so no snapshot here
holds them. Everything else is kept as published, as text.

Not pulled: the resources "Capacity Market Unit (CMU) History" and "Component History". They log changes to every
field, the parent company included, but only from 10 Dec 2025, so they cannot date the owners of 2018-2025; they
also log the changes to the contact fields.

Gotchas: the "Parent Company" is today's (NESO updates it after a sale for every agreement still running), so it
resolves companies to groups, not owners in past years. A CMU row sits under its auction's FIRST delivery year; a
multi-year agreement is found by "Delivery Years for which Agreement Valid" (gbpowerdata.build.build_ownership
.cm_in_force). Applicant names are as declared ("SSE plc" / "SSE Plc").

Output (one snapshot per pull date, never overwritten): data/raw/neso/cm_register/cmu_{YYYYMMDD}.csv and
components_{YYYYMMDD}.csv.

Usage:
  python -m gbpowerdata.pull.cm_register_pull
  python -m gbpowerdata.pull.cm_register_pull --list      # the dataset's resources
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import re
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

CKAN = "https://api.neso.energy/api/3/action"
DATASET = "capacity-market-register"
RESOURCES = {"Capacity Market Unit (CMU)": "cmu", "Components": "components"}
PERSONAL = re.compile(r"contact", re.I)


def out_dir():
    return cfg.raw_dir() / "neso" / "cm_register"


def resources() -> list[dict]:
    r = requests.get(f"{CKAN}/package_show", params={"id": DATASET}, timeout=60)
    r.raise_for_status()
    return r.json()["result"]["resources"]


def download(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            r = requests.get(url, timeout=300)
            r.raise_for_status()
            return r.content
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if i == tries - 1:
                raise
            time.sleep(2 ** i)
    return b""


def without_contacts(data: bytes) -> pd.DataFrame:
    """The published CSV as text, without the contact columns."""
    table = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, encoding="utf-8-sig")
    return table.drop(columns=[c for c in table.columns if PERSONAL.search(c)])


def pull(stamp: str | None = None) -> dict[str, str]:
    """Download the CMU and Components files; returns resource name -> written path."""
    stamp = stamp or dt.date.today().strftime("%Y%m%d")
    out = out_dir()
    out.mkdir(parents=True, exist_ok=True)
    found = {r["name"]: r for r in resources()}
    missing = [n for n in RESOURCES if n not in found]
    if missing:
        raise RuntimeError(f"cm_register_pull: resources not in {DATASET}: {missing}; have {sorted(found)}")
    written = {}
    for name, stem in RESOURCES.items():
        path = out / f"{stem}_{stamp}.csv"
        if path.exists():
            print(f"  {path.name} exists (raw snapshots are immutable), skipped")
            written[name] = str(path)
            continue
        table = without_contacts(download(found[name]["url"]))
        table.to_csv(path, index=False)
        print(f"  {name}: {len(table):,} rows x {table.shape[1]} columns -> {path}")
        written[name] = str(path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="list the dataset's resources and exit")
    a = ap.parse_args(argv)
    if a.list:
        for r in resources():
            print(f"{r['name']:45s} {r.get('format', '')}  {r['url']}")
        return 0
    pull()
    return 0


if __name__ == "__main__":
    sys.exit(main())
