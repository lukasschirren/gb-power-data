"""Pull network charge data from the NESO Data Portal (CKAN REST API).

The National Energy System Operator runs a CKAN portal at api.neso.energy on the
same pattern as the LCCC one - standard REST, no key. This covers the transmission
side of the consumer bill:

  BSUoS   balancing services use of system - fixed tariff (GBP/MWh) plus the
          historic settlement-run data (II/SF/RF)
  AAHEDC  assistance for areas of high electricity distribution costs
  TNUoS   transmission network use of system - we take the DEMAND tariffs
          (non-half-hourly, half-hourly, and the transmission demand residual),
          not the generator tariffs

⚠️ These are OUTTURN published tariffs, i.e. what network users were actually
charged. The corresponding cap ALLOWANCE is in Ofgem Annex 3 (`ofgem_pull`). The
two are not the same number - see bill_decomposition_provenance.md.

⚠️ Distribution (DUoS) is NOT here. It is set per-DNO, published as annual
spreadsheets on 14 separate licensee websites, and has no API - see
data/raw/manual/dno_duos/.

Usage:
  python -m gbpowerdata.pull.neso_pull                      # bsuos + aahedc + tnuos
  python -m gbpowerdata.pull.neso_pull bsuos aahedc         # a subset
  python -m gbpowerdata.pull.neso_pull --list balancing     # search datasets, exit
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd
import requests

from gbpowerdata import config as cfg

CKAN_BASE = "https://api.neso.energy/api/3/action"
OUT_DIR = cfg.raw_dir() / "neso"

# group -> {dataset slug: {resource name fragment: output stem}}
# Resource names are matched case-insensitively on a fragment so a portal rename
# of the trailing text does not break the pull.
DATASETS = {
    "bsuos": {
        "bsuos-fixed-tariffs": {"": "bsuos_fixed_tariffs"},
        "current-balancing-services-use-of-system-bsuos-data": {
            "historic ii bsuos data": "bsuos_historic_ii",
            "historic sf bsuos data": "bsuos_historic_sf",
            "historic rf bsuos data": "bsuos_historic_rf",
        },
    },
    "aahedc": {
        "aahedc-tariffs": {"": "aahedc_tariffs"},
    },
    "tnuos": {
        "transmission-network-use-of-system-tnuos-tariffs": {
            "non half-hourly": "tnuos_demand_nhh",
            "half-hourly (hh) demand": "tnuos_demand_hh",
            "transmission demand residual": "tnuos_demand_residual",
        },
    },
}


def ckan(action: str, **params) -> dict | list:
    r = requests.get(f"{CKAN_BASE}/{action}", params=params, timeout=120)
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error"))
    return payload["result"]


def list_datasets(query: str = "") -> pd.DataFrame:
    res = ckan("package_search", q=query, rows=100)
    return pd.DataFrame([{"name": d["name"], "title": d.get("title", ""),
                          "resources": len(d.get("resources", []))}
                         for d in res["results"]])


def datastore_fetch(resource_id: str, page_size: int = 32_000) -> pd.DataFrame:
    """Rows from a datastore-active resource, paginated with limit/offset."""
    frames, offset = [], 0
    while True:
        res = ckan("datastore_search", resource_id=resource_id,
                   limit=page_size, offset=offset)
        recs = res["records"]
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        offset += len(recs)
        print(f"      {offset:,} / {res['total']:,} rows", flush=True)
        if offset >= res["total"]:
            break
        time.sleep(0.2)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return df.drop(columns="_id", errors="ignore")


def pull_group(group: str) -> None:
    print(f"\n=== {group} ===", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for slug, wanted in DATASETS[group].items():
        pkg = ckan("package_show", id=slug)
        active = [r for r in pkg["resources"] if r.get("datastore_active")]
        if not active:
            print(f"  ! {slug}: no datastore-active resource — skipped", flush=True)
            continue
        for frag, stem in wanted.items():
            matches = [r for r in active if frag.lower() in r["name"].lower()] if frag else active
            if not matches:
                print(f"  ! {slug}: no resource matching '{frag}' — skipped", flush=True)
                continue
            r = matches[0]
            print(f"  {r['name'][:66]}", flush=True)
            df = datastore_fetch(r["id"])
            path = OUT_DIR / f"{stem}.csv"
            df.to_csv(path, index=False)
            print(f"    -> {len(df):,} rows x {df.shape[1]} cols  {path.name}", flush=True)


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(description="Pull network charges from the NESO portal.")
    # No `default=` here: argparse validates a list default against `choices`
    # element-wise and rejects it. Empty means "all", resolved below.
    p.add_argument("groups", nargs="*", choices=list(DATASETS),
                   help="which groups to pull (default: all).")
    p.add_argument("--list", metavar="QUERY", help="search the portal and exit.")
    args = p.parse_args(argv[1:])

    if args.list is not None:
        print(list_datasets(args.list).to_string(index=False))
        return
    for g in (args.groups or list(DATASETS)):
        pull_group(g)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
